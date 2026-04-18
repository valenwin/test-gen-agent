"""Unit tests for llm.client.LLMClient — all Anthropic API calls are mocked."""

from unittest.mock import MagicMock, patch

import pytest

from analyzer.models import ArgumentInfo, CoverageGap, FunctionInfo, ModuleAnalysis
from llm.client import GenerationResult, LLMClient, LLMError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def analysis() -> ModuleAnalysis:
    fn = FunctionInfo(
        name="divide",
        args=[
            ArgumentInfo(name="a", annotation="float"),
            ArgumentInfo(name="b", annotation="float"),
        ],
        return_annotation="float",
        decorators=[],
        docstring=None,
        lineno=1,
        end_lineno=4,
        is_async=False,
        is_method=False,
        complexity=2,
        has_explicit_return=True,
        has_raise=True,
    )
    return ModuleAnalysis(
        filename="math_utils.py",
        functions=[fn],
        classes=[],
        imports=[],
        module_docstring=None,
        coverage_gaps=[
            CoverageGap("divide", "Happy path", "return_value"),
            CoverageGap("divide", "ZeroDivisionError", "exception"),
        ],
    )


SOURCE = "def divide(a, b):\n    if b == 0:\n        raise ValueError\n    return a / b\n"

VALID_TESTS = "def test_divide():\n    assert divide(4, 2) == 2.0\n"


def _make_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    """Build a fake anthropic.types.Message."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    response = MagicMock()
    response.stop_reason = stop_reason
    response.content = [block]
    response.usage.input_tokens = 100
    response.usage.output_tokens = 200
    return response


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestGenerateTests:
    def test_returns_generation_result(self, analysis: ModuleAnalysis) -> None:
        response = _make_response(f"<tests>\n{VALID_TESTS}\n</tests>")
        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = response
            client = LLMClient()
            result = client.generate_tests(SOURCE, analysis)

        assert isinstance(result, GenerationResult)
        assert VALID_TESTS.strip() in result.tests

    def test_attempts_is_1_on_first_success(self, analysis: ModuleAnalysis) -> None:
        response = _make_response(f"<tests>\n{VALID_TESTS}\n</tests>")
        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = response
            client = LLMClient()
            result = client.generate_tests(SOURCE, analysis)

        assert result.attempts == 1

    def test_tokens_are_tracked(self, analysis: ModuleAnalysis) -> None:
        response = _make_response(f"<tests>\n{VALID_TESTS}\n</tests>")
        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = response
            client = LLMClient()
            result = client.generate_tests(SOURCE, analysis)

        assert result.input_tokens == 100
        assert result.output_tokens == 200

    def test_falls_back_to_code_block(self, analysis: ModuleAnalysis) -> None:
        """If Claude returns ```python...``` instead of <tests>, still extract it."""
        response = _make_response(f"```python\n{VALID_TESTS}\n```")
        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = response
            client = LLMClient()
            result = client.generate_tests(SOURCE, analysis)

        assert VALID_TESTS.strip() in result.tests


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

class TestRetry:
    def test_retries_when_no_tests_block(self, analysis: ModuleAnalysis) -> None:
        bad_response = _make_response("Here are your tests: ...")
        good_response = _make_response(f"<tests>\n{VALID_TESTS}\n</tests>")

        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.side_effect = [
                bad_response,
                bad_response,
                good_response,
            ]
            client = LLMClient()
            result = client.generate_tests(SOURCE, analysis)

        # Each API call = one attempt; good response arrives on 3rd call
        assert result.attempts == 3

    def test_raises_llm_error_after_max_retries(self, analysis: ModuleAnalysis) -> None:
        bad_response = _make_response("no tags here")
        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            # Return bad response for every call (initial + retries)
            mock_cls.return_value.messages.create.return_value = bad_response
            client = LLMClient()
            with pytest.raises(LLMError):
                client.generate_tests(SOURCE, analysis)

    def test_previous_error_appended_to_message(self, analysis: ModuleAnalysis) -> None:
        good_response = _make_response(f"<tests>\n{VALID_TESTS}\n</tests>")
        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = good_response
            client = LLMClient()
            client.generate_tests(SOURCE, analysis, previous_error="ImportError: no module")

        call_kwargs = mock_cls.return_value.messages.create.call_args
        messages = call_kwargs.kwargs["messages"]
        user_content = messages[0]["content"]
        assert "ImportError" in user_content


# ---------------------------------------------------------------------------
# Tool calling
# ---------------------------------------------------------------------------

class TestToolCalling:
    def test_handles_get_function_source_tool(self, analysis: ModuleAnalysis) -> None:
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "get_function_source"
        tool_block.id = "tool_abc"
        tool_block.input = {"function_name": "divide"}

        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.content = [tool_block]
        tool_response.usage.input_tokens = 50
        tool_response.usage.output_tokens = 30

        final_response = _make_response(f"<tests>\n{VALID_TESTS}\n</tests>")

        with patch("llm.client.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.side_effect = [
                tool_response,
                final_response,
            ]
            client = LLMClient()
            result = client.generate_tests(SOURCE, analysis)

        assert VALID_TESTS.strip() in result.tests

    def test_unknown_function_returns_not_found_message(self, analysis: ModuleAnalysis) -> None:
        client = LLMClient.__new__(LLMClient)
        msg = client._get_function_source("nonexistent", SOURCE, analysis)
        assert "not found" in msg

    def test_get_function_source_returns_correct_lines(self, analysis: ModuleAnalysis) -> None:
        client = LLMClient.__new__(LLMClient)
        result = client._get_function_source("divide", SOURCE, analysis)
        assert "def divide" in result
        assert "raise ValueError" in result
