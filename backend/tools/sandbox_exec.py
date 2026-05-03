"""Thin wrappers for sandbox execution from HTTP/tools."""
from __future__ import annotations

from backend.sandbox.python_ast import ASTValidationError
from backend.sandbox.python_runner import run_python_subprocess, run_rscript


def execute_code(
    language: str,
    code: str,
    *,
    timeout_sec: int = 120,
) -> dict:
    if language == "python":
        try:
            exit_code, stdout, stderr, plots, violations = run_python_subprocess(code, timeout_sec=timeout_sec)
        except ASTValidationError as e:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": "",
                "plots_base64": [],
                "violations": e.violations,
            }
        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "plots_base64": plots,
            "violations": violations,
        }
    if language == "r":
        try:
            exit_code, stdout, stderr, plots = run_rscript(code, timeout_sec=timeout_sec)
        except RuntimeError as exc:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": str(exc),
                "plots_base64": [],
                "violations": [],
            }
        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "plots_base64": plots,
            "violations": [],
        }
    raise ValueError(f"Unsupported language {language}")
