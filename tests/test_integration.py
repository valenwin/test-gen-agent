"""Integration test: full pipeline from source code to validated tests.

Mocks only the external boundaries (Anthropic API, subprocess).
All internal modules — analyzer, prompt builder, LLM client, validator,
worker task — run for real.
"""

from unittest.mock import MagicMock, patch

import pytest

SOURCE = """\
def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
"""

GENERATED_TESTS = """\
import pytest
from divide import divide


def test_divide_happy_path():
    assert divide(10.0, 2.0) == pytest.approx(5.0)


def test_divide_by_zero_raises():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1.0, 0.0)
"""

PYTEST_OUTPUT = (
    "2 passed in 0.12s\n"
    "TOTAL   10   0   100%\n"
)


def _make_llm_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    response.usage.input_tokens = 500
    response.usage.output_tokens = 300
    return response


def _make_proc(returncode: int, stdout: str) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = ""
    return proc


class TestFullPipeline:
    def test_successful_generation_returns_tests_and_coverage(self) -> None:
        llm_response = _make_llm_response(f"<tests>\n{GENERATED_TESTS}\n</tests>")
        proc = _make_proc(0, PYTEST_OUTPUT)

        with (
            patch("llm.client.anthropic.Anthropic") as mock_anthropic,
            patch("core.validator.subprocess.run", return_value=proc),
        ):
            mock_anthropic.return_value.messages.create.return_value = llm_response

            from worker.tasks import generate_tests_task
            # Call the underlying function directly (bypass Celery broker)
            result = generate_tests_task.__wrapped__(
                code=SOURCE,
                filename="divide.py",
                target_coverage=0.8,
            )

        assert GENERATED_TESTS.strip() in result["tests"]
        assert result["coverage"] == pytest.approx(1.0)
        assert result["attempts"] == 1

    def test_retries_when_coverage_below_target(self) -> None:
        llm_response = _make_llm_response(f"<tests>\n{GENERATED_TESTS}\n</tests>")
        low_cov_proc = _make_proc(0, "1 passed\nTOTAL   10   5   50%\n")
        high_cov_proc = _make_proc(0, PYTEST_OUTPUT)

        with (
            patch("llm.client.anthropic.Anthropic") as mock_anthropic,
            patch("core.validator.subprocess.run", side_effect=[low_cov_proc, high_cov_proc]),
        ):
            mock_anthropic.return_value.messages.create.return_value = llm_response

            from worker.tasks import generate_tests_task
            result = generate_tests_task.__wrapped__(
                code=SOURCE,
                filename="divide.py",
                target_coverage=0.8,
            )

        assert result["attempts"] == 2
        assert result["coverage"] == pytest.approx(1.0)

    def test_returns_best_result_after_max_retries(self) -> None:
        llm_response = _make_llm_response(f"<tests>\n{GENERATED_TESTS}\n</tests>")
        low_cov_proc = _make_proc(0, "1 passed\nTOTAL   10   7   30%\n")

        with (
            patch("llm.client.anthropic.Anthropic") as mock_anthropic,
            patch("core.validator.subprocess.run", return_value=low_cov_proc),
        ):
            mock_anthropic.return_value.messages.create.return_value = llm_response

            from worker.tasks import generate_tests_task
            result = generate_tests_task.__wrapped__(
                code=SOURCE,
                filename="divide.py",
                target_coverage=0.8,
            )

        assert result["validation_error"] == "Tests did not pass after max retries"
        assert GENERATED_TESTS.strip() in result["tests"]

    def test_syntax_error_in_source_propagates(self) -> None:
        from analyzer.parser import AnalysisError
        from worker.tasks import generate_tests_task

        with pytest.raises(AnalysisError):
            generate_tests_task.__wrapped__(
                code="def broken(:\n    pass",
                filename="broken.py",
                target_coverage=0.8,
            )
