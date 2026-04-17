from dataclasses import dataclass, field


@dataclass
class ArgumentInfo:
    name: str
    annotation: str | None = None
    default: str | None = None
    kind: str = "positional"  # positional | keyword_only | var_positional | var_keyword


@dataclass
class FunctionInfo:
    name: str
    args: list[ArgumentInfo]
    return_annotation: str | None
    decorators: list[str]
    docstring: str | None
    lineno: int
    end_lineno: int
    is_async: bool
    is_method: bool
    # Cyclomatic complexity proxy: number of decision points (if/elif/for/while/except/with/and/or)
    complexity: int
    has_explicit_return: bool
    has_raise: bool
    parent_class: str | None = None


@dataclass
class ClassInfo:
    name: str
    bases: list[str]
    decorators: list[str]
    docstring: str | None
    lineno: int
    end_lineno: int
    methods: list[FunctionInfo] = field(default_factory=list)


@dataclass
class ImportInfo:
    module: str | None          # None for `import os` style
    names: list[tuple[str, str | None]]   # (name, alias)
    is_from: bool               # True = "from X import Y"
    lineno: int


@dataclass
class CoverageGap:
    """One testable scenario that needs coverage."""
    function_name: str
    description: str
    gap_type: str   # branch | exception | loop | return_value | async


@dataclass
class ModuleAnalysis:
    filename: str
    functions: list[FunctionInfo]           # top-level functions only
    classes: list[ClassInfo]
    imports: list[ImportInfo]
    module_docstring: str | None
    coverage_gaps: list[CoverageGap]

    @property
    def all_functions(self) -> list[FunctionInfo]:
        """Top-level functions + all class methods."""
        result = list(self.functions)
        for cls in self.classes:
            result.extend(cls.methods)
        return result
