"""Persist optional LLM model override (local sidecar; stored under data_dir)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config import settings

_PREF_NAME = "preferences.json"
_MODEL_RE = re.compile(r"^[a-zA-Z0-9._:/+\-]{1,128}$")


def _path() -> Path:
    return settings.data_dir / _PREF_NAME


def validate_ollama_model_name(name: str) -> str:
    s = name.strip()
    if not s or not _MODEL_RE.fullmatch(s):
        raise ValueError(
            "Model name must be 1–128 characters: letters, digits, and ._:/+- only "
            "(e.g. llama3.2, qwen2.5:7b)."
        )
    return s


def read_ollama_model_override() -> str | None:
    p = _path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("ollama_model")
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip():
        try:
            return validate_ollama_model_name(raw)
        except ValueError:
            return None
    return None


def effective_ollama_model() -> str:
    override = read_ollama_model_override()
    if override:
        return override
    return settings.ollama_model


def env_default_ollama_model() -> str:
    return settings.ollama_model


def set_ollama_model_override(model: str | None) -> None:
    """Persist override, or clear it when model is None or empty after strip."""
    p = _path()
    if model is None or not str(model).strip():
        if not p.is_file():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            data.pop("ollama_model", None)
            if data:
                p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            else:
                p.unlink(missing_ok=True)
        return

    validated = validate_ollama_model_name(str(model))
    data: dict = {}
    if p.is_file():
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                data = prev
        except (json.JSONDecodeError, OSError):
            data = {}
    data["ollama_model"] = validated
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
