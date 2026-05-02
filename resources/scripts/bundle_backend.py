"""Prepare backend tree next to bundled resources (optional, run before tauri build)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TARGET = ROOT / "src-tauri" / "resources" / "backend"


def main() -> None:
    if BACKEND.is_dir():
        if TARGET.exists():
            shutil.rmtree(TARGET)
        shutil.copytree(BACKEND, TARGET, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
        print(f"Copied backend to {TARGET}")


if __name__ == "__main__":
    main()
