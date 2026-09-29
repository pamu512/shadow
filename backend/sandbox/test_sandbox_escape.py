"""Thin checks for audit §02 High #3 (sandbox escape)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.sandbox.python_ast import (
    ASTValidationError,
    SandboxPolicy,
    validate_python_source,
)
from backend.sandbox.python_runner import run_python_subprocess


class TestSandboxAstRejectsOs(unittest.TestCase):
    def test_import_os_is_rejected(self) -> None:
        with self.assertRaises(ASTValidationError) as ctx:
            validate_python_source("import os\n")
        self.assertTrue(any("os" in v for v in ctx.exception.violations))

    def test_os_not_in_default_allowlist(self) -> None:
        self.assertNotIn("os", SandboxPolicy().allowed_import_modules)


class TestSandboxRunnerNoHostFallback(unittest.TestCase):
    def test_no_host_subprocess_when_pyodide_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("backend.sandbox.python_runner.settings") as settings,
                patch("backend.sandbox.python_runner.shutil.which", return_value=None),
                patch("subprocess.run") as host_run,
            ):
                settings.sandbox_mode = "pyodide"
                settings.workspace_dir = Path(tmp)
                rc, _out, err, plots, violations = run_python_subprocess(
                    "print(1)",
                    timeout_sec=5,
                )
                host_run.assert_not_called()
                self.assertNotEqual(rc, 0)
                self.assertTrue(err.strip())
                self.assertEqual(plots, [])
                self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
