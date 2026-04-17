"""AST-based Python code analyzer.

Extracts functions, classes, imports and identifies coverage gaps
that should be targeted during test generation.
"""

import ast
from typing import Any

from analyzer.models import (
    ArgumentInfo,
    ClassInfo,
    CoverageGap,
    FunctionInfo,
    ImportInfo,
    ModuleAnalysis,
)


class AnalysisError(Exception):
    """Raised when the source code cannot be parsed."""


class CodeAnalyzer:
    """Parse a Python source string and extract structured metadata."""

    def analyze(self, source: str, filename: str = "module.py") -> ModuleAnalysis:
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            raise AnalysisError(f"Syntax error in {filename}: {exc}") from exc

        functions: list[FunctionInfo] = []
        classes: list[ClassInfo] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(self._parse_function(node, is_method=False))
            elif isinstance(node, ast.ClassDef):
                classes.append(self._parse_class(node))

        imports = self._collect_imports(tree)
        module_docstring = ast.get_docstring(tree)
        all_functions = functions + [m for cls in classes for m in cls.methods]
        coverage_gaps = self._identify_gaps(all_functions)

        return ModuleAnalysis(
            filename=filename,
            functions=functions,
            classes=classes,
            imports=imports,
            module_docstring=module_docstring,
            coverage_gaps=coverage_gaps,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        is_method: bool,
        parent_class: str | None = None,
    ) -> FunctionInfo:
        args = self._parse_args(node.args)
        decorators = [self._unparse(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)
        return_annotation = self._unparse(node.returns) if node.returns else None
        complexity = self._compute_complexity(node)
        has_explicit_return = self._has_explicit_return(node)
        has_raise = self._has_raise(node)

        return FunctionInfo(
            name=node.name,
            args=args,
            return_annotation=return_annotation,
            decorators=decorators,
            docstring=docstring,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_method=is_method,
            complexity=complexity,
            has_explicit_return=has_explicit_return,
            has_raise=has_raise,
            parent_class=parent_class,
        )

    def _parse_class(self, node: ast.ClassDef) -> ClassInfo:
        bases = [self._unparse(b) for b in node.bases]
        decorators = [self._unparse(d) for d in node.decorator_list]
        docstring = ast.get_docstring(node)
        methods: list[FunctionInfo] = []

        for item in ast.iter_child_nodes(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(
                    self._parse_function(item, is_method=True, parent_class=node.name)
                )

        return ClassInfo(
            name=node.name,
            bases=bases,
            decorators=decorators,
            docstring=docstring,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            methods=methods,
        )

    def _parse_args(self, args: ast.arguments) -> list[ArgumentInfo]:
        result: list[ArgumentInfo] = []

        # Defaults are right-aligned to the positional args list
        n_plain = len(args.args)
        n_defaults = len(args.defaults)
        defaults_offset = n_plain - n_defaults

        for i, arg in enumerate(args.args):
            default_idx = i - defaults_offset
            default = (
                self._unparse(args.defaults[default_idx])
                if default_idx >= 0
                else None
            )
            result.append(ArgumentInfo(
                name=arg.arg,
                annotation=self._unparse(arg.annotation) if arg.annotation else None,
                default=default,
                kind="positional",
            ))

        if args.vararg:
            result.append(ArgumentInfo(
                name=args.vararg.arg,
                annotation=self._unparse(args.vararg.annotation) if args.vararg.annotation else None,
                kind="var_positional",
            ))

        for i, arg in enumerate(args.kwonlyargs):
            default = (
                self._unparse(args.kw_defaults[i])
                if i < len(args.kw_defaults) and args.kw_defaults[i] is not None
                else None
            )
            result.append(ArgumentInfo(
                name=arg.arg,
                annotation=self._unparse(arg.annotation) if arg.annotation else None,
                default=default,
                kind="keyword_only",
            ))

        if args.kwarg:
            result.append(ArgumentInfo(
                name=args.kwarg.arg,
                annotation=self._unparse(args.kwarg.annotation) if args.kwarg.annotation else None,
                kind="var_keyword",
            ))

        return result

    def _collect_imports(self, tree: ast.Module) -> list[ImportInfo]:
        imports: list[ImportInfo] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.append(ImportInfo(
                    module=None,
                    names=[(alias.name, alias.asname) for alias in node.names],
                    is_from=False,
                    lineno=node.lineno,
                ))
            elif isinstance(node, ast.ImportFrom):
                imports.append(ImportInfo(
                    module=node.module,
                    names=[(alias.name, alias.asname) for alias in node.names],
                    is_from=True,
                    lineno=node.lineno,
                ))
        return imports

    def _compute_complexity(self, node: ast.AST) -> int:
        """Count decision points inside a function (cyclomatic complexity proxy)."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (
                ast.If, ast.For, ast.While, ast.ExceptHandler,
                ast.With, ast.AsyncWith, ast.AsyncFor,
                ast.comprehension,
            )):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                # each additional operand in `and`/`or` is a branch
                complexity += len(child.values) - 1
        return complexity

    def _has_explicit_return(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                return True
        return False

    def _has_raise(self, node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                return True
        return False

    def _unparse(self, node: Any) -> str:
        """Convert an AST node back to source text."""
        if node is None:
            return ""
        return ast.unparse(node)

    # ------------------------------------------------------------------
    # Coverage gap detection
    # ------------------------------------------------------------------

    def _identify_gaps(self, functions: list[FunctionInfo]) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []
        for fn in functions:
            qualified = f"{fn.parent_class}.{fn.name}" if fn.parent_class else fn.name
            gaps.extend(self._gaps_for_function(fn, qualified))
        return gaps

    def _gaps_for_function(self, fn: FunctionInfo, qualified_name: str) -> list[CoverageGap]:
        gaps: list[CoverageGap] = []

        # Every function needs at least a happy-path test
        gaps.append(CoverageGap(
            function_name=qualified_name,
            description=f"Happy path: normal execution of `{qualified_name}`",
            gap_type="return_value",
        ))

        if fn.complexity > 2:
            gaps.append(CoverageGap(
                function_name=qualified_name,
                description=(
                    f"Branch coverage: `{qualified_name}` has complexity {fn.complexity} "
                    f"— test each conditional branch"
                ),
                gap_type="branch",
            ))

        if fn.has_raise:
            gaps.append(CoverageGap(
                function_name=qualified_name,
                description=f"Exception path: `{qualified_name}` raises — test error conditions",
                gap_type="exception",
            ))

        if fn.is_async:
            gaps.append(CoverageGap(
                function_name=qualified_name,
                description=f"Async behaviour: `{qualified_name}` is async — test with pytest-asyncio",
                gap_type="async",
            ))

        return gaps