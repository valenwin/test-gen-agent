"""Unit tests for llm.prompt_builder.PromptBuilder."""

import pytest

from analyzer.models import (
    ArgumentInfo,
    ClassInfo,
    CoverageGap,
    FunctionInfo,
    ImportInfo,
    ModuleAnalysis,
)
from llm.prompt_builder import PromptBuilder


@pytest.fixture
def builder() -> PromptBuilder:
    return PromptBuilder()


@pytest.fixture
def simple_function() -> FunctionInfo:
    return FunctionInfo(
        name="add",
        args=[
            ArgumentInfo(name="a", annotation="int"),
            ArgumentInfo(name="b", annotation="int"),
        ],
        return_annotation="int",
        decorators=[],
        docstring="Add two numbers.",
        lineno=1,
        end_lineno=2,
        is_async=False,
        is_method=False,
        complexity=1,
        has_explicit_return=True,
        has_raise=False,
    )


@pytest.fixture
def simple_analysis(simple_function: FunctionInfo) -> ModuleAnalysis:
    return ModuleAnalysis(
        filename="math_utils.py",
        functions=[simple_function],
        classes=[],
        imports=[],
        module_docstring=None,
        coverage_gaps=[
            CoverageGap(
                function_name="add",
                description="Happy path: normal execution of `add`",
                gap_type="return_value",
            )
        ],
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_contains_pytest_rules(self, builder: PromptBuilder) -> None:
        prompt = builder.system_prompt()
        assert "pytest" in prompt
        assert "parametrize" in prompt
        assert "pytest.raises" in prompt

    def test_contains_xml_tag_instruction(self, builder: PromptBuilder) -> None:
        prompt = builder.system_prompt()
        assert "<tests>" in prompt

    def test_contains_few_shot_example(self, builder: PromptBuilder) -> None:
        prompt = builder.system_prompt()
        assert "divide" in prompt  # few-shot example function


# ---------------------------------------------------------------------------
# User message — structure
# ---------------------------------------------------------------------------

class TestUserMessage:
    def test_includes_filename(self, builder: PromptBuilder, simple_analysis: ModuleAnalysis) -> None:
        msg = builder.user_message("def add(a, b): return a + b", simple_analysis)
        assert "math_utils.py" in msg

    def test_includes_function_signature(self, builder: PromptBuilder, simple_analysis: ModuleAnalysis) -> None:
        msg = builder.user_message("def add(a, b): return a + b", simple_analysis)
        assert "def add" in msg
        assert "int" in msg

    def test_includes_coverage_gaps(self, builder: PromptBuilder, simple_analysis: ModuleAnalysis) -> None:
        msg = builder.user_message("def add(a, b): return a + b", simple_analysis)
        assert "return_value" in msg
        assert "Happy path" in msg

    def test_includes_source_code(self, builder: PromptBuilder, simple_analysis: ModuleAnalysis) -> None:
        source = "def add(a, b): return a + b"
        msg = builder.user_message(source, simple_analysis)
        assert source in msg

    def test_includes_xml_reminder(self, builder: PromptBuilder, simple_analysis: ModuleAnalysis) -> None:
        msg = builder.user_message("def add(a, b): return a + b", simple_analysis)
        assert "<tests>" in msg


# ---------------------------------------------------------------------------
# User message — imports
# ---------------------------------------------------------------------------

class TestImportsFormatting:
    def test_plain_import(self, builder: PromptBuilder) -> None:
        analysis = ModuleAnalysis(
            filename="m.py",
            functions=[],
            classes=[],
            imports=[ImportInfo(module=None, names=[("os", None)], is_from=False, lineno=1)],
            module_docstring=None,
            coverage_gaps=[],
        )
        msg = builder.user_message("import os", analysis)
        assert "import os" in msg

    def test_from_import(self, builder: PromptBuilder) -> None:
        analysis = ModuleAnalysis(
            filename="m.py",
            functions=[],
            classes=[],
            imports=[ImportInfo(module="pathlib", names=[("Path", None)], is_from=True, lineno=1)],
            module_docstring=None,
            coverage_gaps=[],
        )
        msg = builder.user_message("from pathlib import Path", analysis)
        assert "from pathlib import Path" in msg

    def test_import_with_alias(self, builder: PromptBuilder) -> None:
        analysis = ModuleAnalysis(
            filename="m.py",
            functions=[],
            classes=[],
            imports=[ImportInfo(module=None, names=[("numpy", "np")], is_from=False, lineno=1)],
            module_docstring=None,
            coverage_gaps=[],
        )
        msg = builder.user_message("import numpy as np", analysis)
        assert "numpy as np" in msg


# ---------------------------------------------------------------------------
# User message — classes
# ---------------------------------------------------------------------------

class TestClassFormatting:
    def test_class_appears_in_message(self, builder: PromptBuilder) -> None:
        method = FunctionInfo(
            name="greet",
            args=[ArgumentInfo(name="self")],
            return_annotation="str",
            decorators=[],
            docstring=None,
            lineno=3,
            end_lineno=4,
            is_async=False,
            is_method=True,
            complexity=1,
            has_explicit_return=True,
            has_raise=False,
            parent_class="Greeter",
        )
        cls = ClassInfo(
            name="Greeter",
            bases=["Base"],
            decorators=[],
            docstring="A greeter.",
            lineno=1,
            end_lineno=4,
            methods=[method],
        )
        analysis = ModuleAnalysis(
            filename="m.py",
            functions=[],
            classes=[cls],
            imports=[],
            module_docstring=None,
            coverage_gaps=[],
        )
        msg = builder.user_message("class Greeter(Base): ...", analysis)
        assert "class Greeter" in msg
        assert "def greet" in msg

    def test_class_bases_shown(self, builder: PromptBuilder) -> None:
        cls = ClassInfo(
            name="Child",
            bases=["Parent"],
            decorators=[],
            docstring=None,
            lineno=1,
            end_lineno=1,
            methods=[],
        )
        analysis = ModuleAnalysis(
            filename="m.py", functions=[], classes=[cls],
            imports=[], module_docstring=None, coverage_gaps=[],
        )
        msg = builder.user_message("class Child(Parent): pass", analysis)
        assert "Parent" in msg


# ---------------------------------------------------------------------------
# Async functions
# ---------------------------------------------------------------------------

class TestAsyncFormatting:
    def test_async_keyword_in_signature(self, builder: PromptBuilder) -> None:
        fn = FunctionInfo(
            name="fetch",
            args=[ArgumentInfo(name="url", annotation="str")],
            return_annotation="str",
            decorators=[],
            docstring=None,
            lineno=1,
            end_lineno=2,
            is_async=True,
            is_method=False,
            complexity=1,
            has_explicit_return=True,
            has_raise=False,
        )
        analysis = ModuleAnalysis(
            filename="m.py", functions=[fn], classes=[],
            imports=[], module_docstring=None, coverage_gaps=[],
        )
        msg = builder.user_message("async def fetch(url): ...", analysis)
        assert "async def fetch" in msg


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_module(self, builder: PromptBuilder) -> None:
        analysis = ModuleAnalysis(
            filename="empty.py", functions=[], classes=[],
            imports=[], module_docstring=None, coverage_gaps=[],
        )
        msg = builder.user_message("", analysis)
        assert "empty.py" in msg
        assert "No specific gaps" in msg

    def test_no_gaps_fallback_message(self, builder: PromptBuilder) -> None:
        analysis = ModuleAnalysis(
            filename="m.py", functions=[], classes=[],
            imports=[], module_docstring=None, coverage_gaps=[],
        )
        msg = builder.user_message("pass", analysis)
        assert "No specific gaps" in msg
