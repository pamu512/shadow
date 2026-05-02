"""AST-based validation policy for user/agent Python code."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class SandboxPolicy:
    max_lines: int = 2000
    allowed_import_modules: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "polars",
                "pandas",
                "numpy",
                "matplotlib",
                "os",
                "math",
                "json",
                "re",
                "datetime",
                "collections",
                "itertools",
                "statistics",
                "random",
            }
        )
    )
    banned_names: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "open",
                "exec",
                "eval",
                "compile",
                "__import__",
                "breakpoint",
                "input",
                "globals",
                "locals",
                "vars",
                "dir",
                "getattr",
                "setattr",
                "delattr",
            }
        )
    )


DEFAULT_POLICY = SandboxPolicy()


class ASTValidationError(Exception):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("\n".join(violations))


class PythonASTValidator(ast.NodeVisitor):
    def __init__(self, policy: SandboxPolicy = DEFAULT_POLICY):
        self.policy = policy
        self.violations: list[str] = []

    def _add(self, msg: str, node: ast.AST) -> None:
        lineno = getattr(node, "lineno", "?")
        self.violations.append(f"L{lineno}: {msg}")

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base not in self.policy.allowed_import_modules:
                self._add(f"import '{alias.name}' is not allowed", node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module is None:
            self._add("relative import is not allowed", node)
            return
        base = node.module.split(".")[0]
        if base not in self.policy.allowed_import_modules:
            self._add(f"import from '{node.module}' is not allowed", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if isinstance(node.attr, str) and node.attr.startswith("__"):
            self._add(f"dunder attribute access '{node.attr}' is not allowed", node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        name = _call_name(node.func)
        if name and name in self.policy.banned_names:
            self._add(f"call to '{name}' is not allowed", node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if isinstance(node.ctx, ast.Load) and node.id in self.policy.banned_names:
            self._add(f"reference to '{node.id}' is not allowed", node)
        self.generic_visit(node)


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def validate_python_source(source: str, policy: SandboxPolicy = DEFAULT_POLICY) -> None:
    lines = source.splitlines()
    if len(lines) > policy.max_lines:
        raise ASTValidationError([f"Too many lines ({len(lines)} > {policy.max_lines})"])
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as e:
        raise ASTValidationError([f"Syntax error: {e}"]) from e
    validator = PythonASTValidator(policy)
    validator.visit(tree)
    if validator.violations:
        raise ASTValidationError(validator.violations)
