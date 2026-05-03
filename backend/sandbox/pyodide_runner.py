"""Pyodide (WASM) execution via Node.js."""
from __future__ import annotations

import subprocess
from pathlib import Path


def run_python_in_pyodide(
    script_path: Path,
    *,
    timeout_sec: int,
    workspace: Path,
    dataset_path: str,
) -> tuple[int, str, str]:
    """Run a .py file inside Pyodide WASM via Node.js."""
    runner_script = Path(__file__).resolve().parent / "run_pyodide.mjs"
    
    cmd = [
        "node",
        str(runner_script),
        str(script_path),
        dataset_path or "None",
    ]
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(workspace),
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "Execution timed out"
