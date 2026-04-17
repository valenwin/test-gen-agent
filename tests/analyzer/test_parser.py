"""Unit tests for analyzer.parser.CodeAnalyzer."""

import pytest

from analyzer.models import ModuleAnalysis
from analyzer.parser import AnalysisError, CodeAnalyzer


@pytest.fixture
def analyzer() -> CodeAnalyzer:
    return CodeAnalyzer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def analyze(source: str, filename: str = "test_module.py") -> ModuleAnalysis:
    return CodeAnalyzer().analyze(source, filename)


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------

class TestBasicParsing:
    def test_empty_module(self, analyzer: CodeAnalyzer) -> None:
        result = analyzer.analyze("", "empty.py")
        assert result.filename == "empty.py"
        assert result.functions == []
        assert result.classes == []
        assert result.imports == []
        assert result.module_docstring is None

    def test_module_docstring(self) -> None:
        result = analyze('"""My module."""\n')
        assert result.module_docstring == "My module."

    def test_syntax_error_raises(self, analyzer: CodeAnalyzer) -> None:
        with pytest.raises(AnalysisError, match="Syntax error"):
            analyzer.analyze("def broken(:\n    pass")


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------

class TestFunctionExtraction:
    def test_simple_function(self) -> None:
        src = "def add(a: int, b: int) -> int:\n    return a + b\n"
        result = analyze(src)
        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "add"
        assert fn.return_annotation == "int"
        assert not fn.is_async
        assert not fn.is_method
        assert fn.has_explicit_return

    def test_async_function(self) -> None:
        src = "async def fetch(url: str) -> str:\n    return url\n"
        fn = analyze(src).functions[0]
        assert fn.is_async
        assert fn.name == "fetch"

    def test_function_with_default_arg(self) -> None:
        src = "def greet(name: str = 'world') -> str:\n    return f'hi {name}'\n"
        fn = analyze(src).functions[0]
        arg = fn.args[0]
        assert arg.name == "name"
        assert arg.annotation == "str"
        assert arg.default == "'world'"

    def test_function_with_varargs(self) -> None:
        src = "def fn(*args, **kwargs): pass\n"
        fn = analyze(src).functions[0]
        kinds = {a.name: a.kind for a in fn.args}
        assert kinds["args"] == "var_positional"
        assert kinds["kwargs"] == "var_keyword"

    def test_function_with_kwonly_arg(self) -> None:
        src = "def fn(a, *, key: str = 'x'): pass\n"
        fn = analyze(src).functions[0]
        kwonly = next(a for a in fn.args if a.kind == "keyword_only")
        assert kwonly.name == "key"
        assert kwonly.default == "'x'"

    def test_function_decorators(self) -> None:
        src = "@staticmethod\n@my_decorator\ndef fn(): pass\n"
        fn = analyze(src).functions[0]
        assert "staticmethod" in fn.decorators
        assert "my_decorator" in fn.decorators

    def test_function_has_raise(self) -> None:
        src = "def fn(x):\n    if not x:\n        raise ValueError('bad')\n"
        fn = analyze(src).functions[0]
        assert fn.has_raise

    def test_function_no_return(self) -> None:
        src = "def fn(): pass\n"
        fn = analyze(src).functions[0]
        assert not fn.has_explicit_return
        assert fn.return_annotation is None

    def test_function_line_numbers(self) -> None:
        src = "def fn():\n    pass\n"
        fn = analyze(src).functions[0]
        assert fn.lineno == 1
        assert fn.end_lineno == 2


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

class TestClassExtraction:
    def test_simple_class(self) -> None:
        src = "class Foo:\n    pass\n"
        result = analyze(src)
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "Foo"
        assert cls.bases == []

    def test_class_with_base(self) -> None:
        src = "class Bar(Base, Mixin):\n    pass\n"
        cls = analyze(src).classes[0]
        assert "Base" in cls.bases
        assert "Mixin" in cls.bases

    def test_class_methods_extracted(self) -> None:
        src = (
            "class MyClass:\n"
            "    def method_a(self): pass\n"
            "    async def method_b(self): pass\n"
        )
        cls = analyze(src).classes[0]
        names = [m.name for m in cls.methods]
        assert "method_a" in names
        assert "method_b" in names

    def test_method_marked_as_method(self) -> None:
        src = "class C:\n    def fn(self): pass\n"
        method = analyze(src).classes[0].methods[0]
        assert method.is_method
        assert method.parent_class == "C"

    def test_class_docstring(self) -> None:
        src = 'class C:\n    """Docstring."""\n    pass\n'
        cls = analyze(src).classes[0]
        assert cls.docstring == "Docstring."

    def test_all_functions_includes_methods(self) -> None:
        src = (
            "def top(): pass\n"
            "class C:\n"
            "    def method(self): pass\n"
        )
        result = analyze(src)
        names = [f.name for f in result.all_functions]
        assert "top" in names
        assert "method" in names


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

class TestImportExtraction:
    def test_plain_import(self) -> None:
        result = analyze("import os\n")
        imp = result.imports[0]
        assert imp.module is None
        assert ("os", None) in imp.names
        assert not imp.is_from

    def test_from_import(self) -> None:
        result = analyze("from pathlib import Path\n")
        imp = result.imports[0]
        assert imp.module == "pathlib"
        assert ("Path", None) in imp.names
        assert imp.is_from

    def test_import_alias(self) -> None:
        result = analyze("import numpy as np\n")
        imp = result.imports[0]
        assert ("numpy", "np") in imp.names

    def test_multiple_imports(self) -> None:
        src = "import os\nimport sys\nfrom pathlib import Path\n"
        result = analyze(src)
        assert len(result.imports) == 3


# ---------------------------------------------------------------------------
# Complexity & coverage gaps
# ---------------------------------------------------------------------------

class TestComplexity:
    def test_simple_function_complexity_is_1(self) -> None:
        src = "def fn(): pass\n"
        fn = analyze(src).functions[0]
        assert fn.complexity == 1

    def test_if_increases_complexity(self) -> None:
        src = "def fn(x):\n    if x:\n        return 1\n    return 0\n"
        fn = analyze(src).functions[0]
        assert fn.complexity == 2

    def test_bool_op_increases_complexity(self) -> None:
        src = "def fn(a, b, c):\n    return a and b and c\n"
        fn = analyze(src).functions[0]
        # BoolOp with 3 values → 2 extra branches
        assert fn.complexity == 3

    def test_for_loop_increases_complexity(self) -> None:
        src = "def fn(items):\n    for i in items:\n        pass\n"
        fn = analyze(src).functions[0]
        assert fn.complexity == 2

    def test_try_except_increases_complexity(self) -> None:
        src = (
            "def fn():\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        pass\n"
        )
        fn = analyze(src).functions[0]
        assert fn.complexity >= 2


class TestCoverageGaps:
    def test_every_function_has_happy_path_gap(self) -> None:
        src = "def fn(): pass\n"
        gaps = analyze(src).coverage_gaps
        happy = [g for g in gaps if g.gap_type == "return_value"]
        assert len(happy) == 1
        assert "fn" in happy[0].function_name

    def test_complex_function_gets_branch_gap(self) -> None:
        src = (
            "def fn(x):\n"
            "    if x > 0:\n"
            "        if x > 10:\n"
            "            return 'big'\n"
            "        return 'small'\n"
            "    return 'neg'\n"
        )
        gaps = analyze(src).coverage_gaps
        branch_gaps = [g for g in gaps if g.gap_type == "branch"]
        assert len(branch_gaps) == 1

    def test_raising_function_gets_exception_gap(self) -> None:
        src = "def fn(x):\n    if not x:\n        raise ValueError\n"
        gaps = analyze(src).coverage_gaps
        exc_gaps = [g for g in gaps if g.gap_type == "exception"]
        assert len(exc_gaps) == 1

    def test_async_function_gets_async_gap(self) -> None:
        src = "async def fn(): pass\n"
        gaps = analyze(src).coverage_gaps
        async_gaps = [g for g in gaps if g.gap_type == "async"]
        assert len(async_gaps) == 1

    def test_method_gap_includes_class_name(self) -> None:
        src = "class C:\n    def method(self): pass\n"
        gaps = analyze(src).coverage_gaps
        assert any("C.method" in g.function_name for g in gaps)

    def test_no_gaps_for_empty_module(self) -> None:
        result = analyze("")
        assert result.coverage_gaps == []
