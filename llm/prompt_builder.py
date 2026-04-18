"""Builds prompts for Claude from ModuleAnalysis."""

from analyzer.models import ClassInfo, FunctionInfo, ImportInfo, ModuleAnalysis

# ---------------------------------------------------------------------------
# Few-shot examples embedded in the system prompt
# ---------------------------------------------------------------------------

_FEW_SHOT = '''
## Example

Input function:
```python
def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

Output:
<tests>
import pytest
from module import divide


def test_divide_returns_correct_result():
    assert divide(10.0, 2.0) == 5.0


def test_divide_by_zero_raises_value_error():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1.0, 0.0)


@pytest.mark.parametrize("a,b,expected", [
    (6.0, 3.0, 2.0),
    (-4.0, 2.0, -2.0),
    (0.0, 5.0, 0.0),
])
def test_divide_parametrized(a, b, expected):
    assert divide(a, b) == expected
</tests>
'''

_SYSTEM_PROMPT = f"""\
You are an expert Python test engineer. Your job is to generate comprehensive pytest tests.

Rules:
- Use pytest (never unittest)
- Use fixtures for repeated setup
- Use @pytest.mark.parametrize for multiple input variants
- Use pytest.raises for exception paths
- Use unittest.mock.patch / MagicMock for external dependencies
- For async functions use @pytest.mark.asyncio
- Each test function name must describe what it tests: test_<function>_<scenario>
- Import only what is needed
- Do NOT test private helpers (_name) unless explicitly asked
- Output ONLY the test code wrapped in <tests>...</tests> XML tags, nothing else

{_FEW_SHOT}
"""


class PromptBuilder:
    """Converts a ModuleAnalysis into Claude prompt messages."""

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def user_message(self, source: str, analysis: ModuleAnalysis) -> str:
        parts: list[str] = []

        parts.append(f"Generate pytest tests for `{analysis.filename}`.\n")

        if analysis.imports:
            parts.append("### Imports in the module")
            parts.append(self._format_imports(analysis.imports))

        if analysis.functions:
            parts.append("### Top-level functions")
            for fn in analysis.functions:
                parts.append(self._format_function(fn))

        if analysis.classes:
            parts.append("### Classes")
            for cls in analysis.classes:
                parts.append(self._format_class(cls))

        parts.append("### Coverage gaps to target")
        if analysis.coverage_gaps:
            for gap in analysis.coverage_gaps:
                parts.append(f"- [{gap.gap_type}] {gap.description}")
        else:
            parts.append("- No specific gaps detected — cover the happy path.")

        parts.append("### Full source code")
        parts.append(f"```python\n{source}\n```")

        parts.append(
            "Now generate the tests. Remember: output ONLY the code inside <tests>...</tests>."
        )

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_function(self, fn: FunctionInfo, indent: str = "") -> str:
        decorators = "".join(f"{indent}@{d}\n" for d in fn.decorators)
        async_kw = "async " if fn.is_async else ""
        args = ", ".join(self._format_arg(a) for a in fn.args)
        ret = f" -> {fn.return_annotation}" if fn.return_annotation else ""
        sig = f"{indent}{decorators}{indent}{async_kw}def {fn.name}({args}){ret}"
        lines = [sig]
        if fn.docstring:
            lines.append(f'{indent}    """{fn.docstring}"""')
        lines.append(f"{indent}    complexity={fn.complexity}")
        return "\n".join(lines)

    def _format_arg(self, arg) -> str:  # type: ignore[no-untyped-def]
        prefix = {"var_positional": "*", "var_keyword": "**"}.get(arg.kind, "")
        annotation = f": {arg.annotation}" if arg.annotation else ""
        default = f" = {arg.default}" if arg.default is not None else ""
        return f"{prefix}{arg.name}{annotation}{default}"

    def _format_class(self, cls: ClassInfo) -> str:
        bases = f"({', '.join(cls.bases)})" if cls.bases else ""
        lines = [f"class {cls.name}{bases}:"]
        if cls.docstring:
            lines.append(f'    """{cls.docstring}"""')
        for method in cls.methods:
            lines.append(self._format_function(method, indent="    "))
        return "\n".join(lines)

    def _format_imports(self, imports: list[ImportInfo]) -> str:
        lines = []
        for imp in imports:
            if imp.is_from:
                names = ", ".join(
                    f"{name} as {alias}" if alias else name
                    for name, alias in imp.names
                )
                lines.append(f"from {imp.module} import {names}")
            else:
                names = ", ".join(
                    f"{name} as {alias}" if alias else name
                    for name, alias in imp.names
                )
                lines.append(f"import {names}")
        return "\n".join(lines)