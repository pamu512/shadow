"""Execute validated Python in subprocess with workspace cwd."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from backend.config import settings
from backend.sandbox.python_ast import SandboxPolicy, validate_python_source


def _output_dir() -> Path:
    d = settings.workspace_dir / ".output" / f"run_{uuid.uuid4().hex}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_python_subprocess(
    code: str,
    *,
    timeout_sec: int = 120,
    policy: SandboxPolicy | None = None,
) -> tuple[int, str, str, list[str], list[str]]:
    policy = policy or SandboxPolicy()
    validate_python_source(code, policy)
    out_dir = _output_dir()
    env = os.environ.copy()
    env["FRAUD_PLOT_DIR"] = str(out_dir)
    env["MPLBACKEND"] = "Agg"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
        dir=settings.workspace_dir,
    ) as tmp:
        tmp.write(
            "import os\n"
            f"PLOT_DIR = os.environ['FRAUD_PLOT_DIR']\n"
            "DATASET_PATH = os.environ.get('FRAUD_DATASET_PATH', '')\n"
            + code
            + "\n"
        )
        script_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(settings.workspace_dir),
            env=env,
        )
        plots: list[str] = []
        for png in sorted(out_dir.glob("*.png")):
            plots.append(base64.b64encode(png.read_bytes()).decode("ascii"))
        violations: list[str] = []
        return proc.returncode, proc.stdout or "", proc.stderr or "", plots, violations
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except OSError:
            pass


def run_rscript(
    code: str,
    *,
    timeout_sec: int = 120,
) -> tuple[int, str, str, list[str]]:
    out_dir = _output_dir()
    env = os.environ.copy()
    env["FRAUD_PLOT_DIR"] = str(out_dir)
    header = f"Sys.setenv(FRAUD_PLOT_DIR = {json.dumps(str(out_dir))})\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".R",
        delete=False,
        encoding="utf-8",
        dir=settings.workspace_dir,
    ) as tmp:
        tmp.write(header + code + "\n")
        script_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            ["Rscript", str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(settings.workspace_dir),
            env=env,
        )
        plots = []
        for png in sorted(out_dir.glob("*.png")):
            plots.append(base64.b64encode(png.read_bytes()).decode("ascii"))
        return proc.returncode, proc.stdout or "", proc.stderr or "", plots
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except OSError:
            pass
