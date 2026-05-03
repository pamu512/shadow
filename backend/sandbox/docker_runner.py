"""Optional Docker-isolated execution (--network none, memory cap) for Python / R.

Mounts only the ephemeral script (read-only), plot output dir (read-write), and optional
dataset path (read-only). Does not mount the full workspace.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from backend.config import settings


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _dataset_volume_args(env: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """Extra ``docker run -v`` flags and env overrides so FRAUD_DATASET_PATH points inside the container."""
    extra: list[str] = []
    out_env = dict(env)
    raw = (env.get("FRAUD_DATASET_PATH") or "").strip()
    if not raw:
        return extra, out_env
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        return extra, out_env
    if p.is_file():
        extra.extend(["-v", f"{p}:/sandbox/dataset_source:ro"])
        out_env["FRAUD_DATASET_PATH"] = "/sandbox/dataset_source"
    else:
        extra.extend(["-v", f"{p}:/sandbox/dataset_dir:ro"])
        out_env["FRAUD_DATASET_PATH"] = "/sandbox/dataset_dir"
    return extra, out_env


def run_python_in_docker(
    script_body: str,
    *,
    timeout_sec: int,
    workspace: Path,
    plot_dir: Path,
    env: dict[str, str],
) -> tuple[int, str, str]:
    """Run a .py file in a container with minimal mounts (script ro, plots rw, dataset ro if set)."""
    sid = uuid.uuid4().hex
    script_name = f".shadow_run_{sid}.py"
    script_path = workspace / script_name
    workspace.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_body, encoding="utf-8")
    plot_dir.mkdir(parents=True, exist_ok=True)
    ds_vols, env_in = _dataset_volume_args(env)
    try:
        cmd: list[str] = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-m",
            "768m",
            "--cpus",
            "1.0",
            "--storage-opt",
            "size=1G",
            "--pids-limit",
            "100",
            "--ulimit",
            "nofile=50:50",
            "-v",
            f"{script_path.resolve()}:/sandbox/run.py:ro",
            "-v",
            f"{plot_dir.resolve()}:/plots:rw",
            *ds_vols,
            "-w",
            "/sandbox",
            "-e",
            "FRAUD_PLOT_DIR=/plots",
            "-e",
            "MPLBACKEND=Agg",
            "-e",
            f"FRAUD_DATASET_PATH={env_in.get('FRAUD_DATASET_PATH', '')}",
            settings.sandbox_docker_image,
            "python3",
            "/sandbox/run.py",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 30,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except OSError:
            pass


def run_r_in_docker(
    script_body: str,
    *,
    timeout_sec: int,
    workspace: Path,
    plot_dir: Path,
    dataset_path: str | None = None,
) -> tuple[int, str, str]:
    """Run R with minimal mounts (script ro, plots rw, optional dataset ro)."""
    sid = uuid.uuid4().hex
    script_name = f".shadow_run_{sid}.R"
    script_path = workspace / script_name
    header = "Sys.setenv(FRAUD_PLOT_DIR = '/plots')\n"
    script_path.write_text(header + script_body + "\n", encoding="utf-8")
    workspace.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)
    env_map: dict[str, str] = {}
    if dataset_path:
        env_map["FRAUD_DATASET_PATH"] = dataset_path
    ds_vols, env_in = _dataset_volume_args(env_map)
    try:
        cmd: list[str] = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-m",
            "768m",
            "--cpus",
            "1.0",
            "--storage-opt",
            "size=1G",
            "--pids-limit",
            "100",
            "--ulimit",
            "nofile=50:50",
            "-v",
            f"{script_path.resolve()}:/sandbox/run.R:ro",
            "-v",
            f"{plot_dir.resolve()}:/plots:rw",
            *ds_vols,
            "-w",
            "/sandbox",
            "-e",
            f"FRAUD_DATASET_PATH={env_in.get('FRAUD_DATASET_PATH', '')}",
            settings.sandbox_docker_r_image,
            "Rscript",
            "/sandbox/run.R",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 30,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except OSError:
            pass
