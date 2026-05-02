"""Ollama connectivity check."""
from __future__ import annotations

import httpx

from backend.config import settings


def _ollama_native_base() -> str:
    base = settings.ollama_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base or "http://127.0.0.1:11434"


async def ollama_reachable() -> bool:
    base = _ollama_native_base()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{base}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def fetch_ollama_model_names() -> tuple[list[str], str | None]:
    """Return sorted unique model names from Ollama ``/api/tags``, or ([], error)."""
    base = _ollama_native_base()
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{base}/api/tags")
            if r.status_code != 200:
                return [], f"Ollama returned HTTP {r.status_code}"
            data = r.json()
            raw = data.get("models") or []
            names: list[str] = []
            for m in raw:
                if not isinstance(m, dict):
                    continue
                name = m.get("name") or m.get("model")
                if name:
                    names.append(str(name).strip())
            return sorted(set(names)), None
    except Exception as e:
        return [], str(e) or "Could not reach Ollama"
