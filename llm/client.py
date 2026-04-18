"""Anthropic Claude client with tool calling and retry loop."""

import re
from dataclasses import dataclass, field

import anthropic

from analyzer.models import ModuleAnalysis
from config import get_settings
from core.logging import logger
from llm.prompt_builder import PromptBuilder

# Tool that Claude can call to inspect a specific function's source
_GET_SOURCE_TOOL = {
    "name": "get_function_source",
    "description": (
        "Returns the full source code of a specific function or method "
        "from the module being analyzed. Use this when you need to see "
        "the implementation details before writing tests."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "function_name": {
                "type": "string",
                "description": "Function or method name, e.g. 'my_func' or 'MyClass.my_method'",
            }
        },
        "required": ["function_name"],
    },
}


@dataclass
class GenerationResult:
    tests: str
    attempts: int
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _ConversationState:
    """Mutable state for one generation attempt."""
    messages: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient:
    """Wraps the Anthropic SDK. Handles tool calling and retry on failure."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model
        self._max_tokens = settings.anthropic_max_tokens
        self._max_retries = settings.max_retries
        self._builder = PromptBuilder()

    def generate_tests(
        self,
        source: str,
        analysis: ModuleAnalysis,
        previous_error: str | None = None,
    ) -> GenerationResult:
        """Generate tests for the given source code.

        Args:
            source: Raw Python source code.
            analysis: Parsed module analysis from CodeAnalyzer.
            previous_error: Pytest error from the last failed attempt (for retry).

        Returns:
            GenerationResult with the extracted test code.
        """
        log = logger.bind(filename=analysis.filename, model=self._model)
        state = _ConversationState()

        user_content = self._builder.user_message(source, analysis)
        if previous_error:
            user_content += (
                f"\n\n### Previous attempt failed\n"
                f"The tests you generated produced the following error:\n"
                f"```\n{previous_error}\n```\n"
                f"Fix the issues and regenerate all tests."
            )

        state.messages.append({"role": "user", "content": user_content})

        for attempt in range(1, self._max_retries + 1):
            log.info("llm_call", attempt=attempt)
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._builder.system_prompt(),
                tools=[_GET_SOURCE_TOOL],
                messages=state.messages,
            )
            state.input_tokens += response.usage.input_tokens
            state.output_tokens += response.usage.output_tokens

            # Handle tool calls in a loop until Claude gives a final answer
            while response.stop_reason == "tool_use":
                tool_results = self._handle_tool_calls(response, source, analysis)
                state.messages.append({"role": "assistant", "content": response.content})
                state.messages.append({"role": "user", "content": tool_results})

                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=self._builder.system_prompt(),
                    tools=[_GET_SOURCE_TOOL],
                    messages=state.messages,
                )
                state.input_tokens += response.usage.input_tokens
                state.output_tokens += response.usage.output_tokens

            raw_text = self._extract_text(response)
            tests = self._extract_tests_block(raw_text)

            if tests:
                log.info("llm_success", attempt=attempt, output_tokens=state.output_tokens)
                return GenerationResult(
                    tests=tests,
                    attempts=attempt,
                    model=self._model,
                    input_tokens=state.input_tokens,
                    output_tokens=state.output_tokens,
                )

            log.warning("llm_no_tests_block", attempt=attempt, raw=raw_text[:200])
            # Ask Claude to fix the format
            state.messages.append({"role": "assistant", "content": raw_text})
            state.messages.append({
                "role": "user",
                "content": "Your response didn't contain a <tests>...</tests> block. Please output the tests wrapped in those tags.",
            })

        raise LLMError(f"Failed to generate valid tests after {self._max_retries} attempts")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _handle_tool_calls(
        self,
        response: anthropic.types.Message,
        source: str,
        analysis: ModuleAnalysis,
    ) -> list[dict]:
        """Execute tool calls and return tool result blocks."""
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "get_function_source":
                fn_name: str = block.input.get("function_name", "")
                result = self._get_function_source(fn_name, source, analysis)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        return results

    def _get_function_source(
        self,
        function_name: str,
        source: str,
        analysis: ModuleAnalysis,
    ) -> str:
        """Extract source lines for a named function/method."""
        # Look in top-level functions and class methods
        target = None
        for fn in analysis.all_functions:
            qualified = f"{fn.parent_class}.{fn.name}" if fn.parent_class else fn.name
            if qualified == function_name or fn.name == function_name:
                target = fn
                break

        if target is None:
            return f"Function `{function_name}` not found in the module."

        lines = source.splitlines()
        start = target.lineno - 1
        end = target.end_lineno
        return "\n".join(lines[start:end])

    def _extract_text(self, response: anthropic.types.Message) -> str:
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    def _extract_tests_block(self, text: str) -> str:
        """Pull code from <tests>...</tests> tags."""
        match = re.search(r"<tests>(.*?)</tests>", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback: if response is a plain code block with no XML tags
        match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""


class LLMError(Exception):
    """Raised when the LLM fails to produce valid output."""
