"""Execute validated Python in subprocess with workspace cwd."""
from __future__ import annotations

import base64
import os
import shutil
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
    script_body = (
        "import os\n"
        f"PLOT_DIR = os.environ['FRAUD_PLOT_DIR']\n"
        "DATASET_PATH = os.environ.get('FRAUD_DATASET_PATH', '')\n"
        + code
        + "\n"
    )
    use_docker = settings.sandbox_mode == "docker" and shutil.which("docker") is not None
    use_pyodide = settings.sandbox_mode == "pyodide" and shutil.which("node") is not None
    
    if use_docker:
        from backend.sandbox.docker_runner import run_python_in_docker

        try:
            rc, out, err = run_python_in_docker(
                script_body,
                timeout_sec=timeout_sec,
                workspace=settings.workspace_dir,
                plot_dir=out_dir,
                env=env,
            )
            plots = [base64.b64encode(png.read_bytes()).decode("ascii") for png in sorted(out_dir.glob("*.png"))]
            return rc, out, err, plots, []
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
        
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
        dir=settings.workspace_dir,
    ) as tmp:
        tmp.write(script_body)
        script_path = Path(tmp.name)
        
    try:
        if use_pyodide:
            from backend.sandbox.pyodide_runner import run_python_in_pyodide
            rc, out, err = run_python_in_pyodide(
                script_path,
                timeout_sec=timeout_sec,
                workspace=settings.workspace_dir,
                dataset_path=env.get("FRAUD_DATASET_PATH", ""),
            )
        else:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=str(settings.workspace_dir),
                env=env,
            )
            rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
            
        plots = [base64.b64encode(png.read_bytes()).decode("ascii") for png in sorted(out_dir.glob("*.png"))]
        violations: list[str] = []
        return rc, out, err, plots, violations
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
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
    # Python uses Pyodide in pyodide mode; R has no WASM path — use Docker when available for isolation.
    use_docker = settings.sandbox_mode == "docker" and shutil.which("docker") is not None
    if settings.sandbox_mode == "pyodide" and shutil.which("docker") is not None:
        use_docker = True
    if use_docker:
        from backend.sandbox.docker_runner import run_r_in_docker

        try:
            rc, out, err = run_r_in_docker(
                code,
                timeout_sec=timeout_sec,
                workspace=settings.workspace_dir,
                plot_dir=out_dir,
                dataset_path=env.get("FRAUD_DATASET_PATH") or None,
            )
            plots = [base64.b64encode(png.read_bytes()).decode("ascii") for png in sorted(out_dir.glob("*.png"))]
            return rc, out, err, plots
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    raise RuntimeError(
        "Isolated R execution requires Docker. Install Docker and configure SHADOW_SANDBOX_DOCKER_R_IMAGE "
        "(see CONFIGURATION.md), then set SHADOW_SANDBOX_MODE=docker or use default pyodide with Docker available "
        "for R. Host Rscript execution is disabled for security."
    )
