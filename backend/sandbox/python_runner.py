"""Execute validated Python in subprocess with workspace cwd."""
from __future__ import annotations

import base64
import os
import shutil
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
    # ponytail: bind only plot/dataset paths; do not leave `os` in user globals (upgrade: pathlib helper)
    script_body = (
        "PLOT_DIR = __import__('os').environ['FRAUD_PLOT_DIR']\n"
        "DATASET_PATH = __import__('os').environ.get('FRAUD_DATASET_PATH', '')\n"
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

    if not use_pyodide:
        shutil.rmtree(out_dir, ignore_errors=True)
        return (
            1,
            "",
            "Sandbox backend unavailable: isolated Python requires "
            "SHADOW_SANDBOX_MODE=pyodide with Node.js on PATH, or "
            "SHADOW_SANDBOX_MODE=docker with Docker on PATH. "
            "Host subprocess execution is disabled.",
            [],
            [],
        )

    cwd_dir = settings.workspace_dir / f"cwd_{uuid.uuid4().hex}"
    cwd_dir.mkdir(parents=True, exist_ok=True)
    script_path = cwd_dir / f"run_{uuid.uuid4().hex}.py"
    script_path.write_text(script_body, encoding="utf-8")

    try:
        from backend.sandbox.pyodide_runner import run_python_in_pyodide

        rc, out, err = run_python_in_pyodide(
            script_path,
            timeout_sec=timeout_sec,
            workspace=cwd_dir,
            dataset_path=env.get("FRAUD_DATASET_PATH", ""),
        )

        plots = [base64.b64encode(png.read_bytes()).decode("ascii") for png in sorted(out_dir.glob("*.png"))]
        violations: list[str] = []
        return rc, out, err, plots, violations
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(cwd_dir, ignore_errors=True)


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
