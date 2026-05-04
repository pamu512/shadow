"""Ollama embedding helper (shared with supervisor semantic router)."""
from __future__ import annotations

import math
from typing import Sequence

import httpx

from backend.config import settings
from backend.llm_preferences import effective_ollama_model


def ollama_embeddings_base() -> str:
    u = (settings.ollama_base_url or "").strip().rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3]
    return u or "http://localhost:11434"


def embed_one(text: str, *, timeout: float = 90.0) -> list[float] | None:
    t = (text or "").strip()[:8000]
    if not t:
        return None
    url = f"{ollama_embeddings_base()}/api/embeddings"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json={"model": effective_ollama_model(), "prompt": t})
            if r.status_code != 200:
                return None
            emb = r.json().get("embedding")
            if not isinstance(emb, list) or not emb:
                return None
            return [float(x) for x in emb]
    except Exception:
        return None


def l2_normalize(v: Sequence[float]) -> list[float]:
    s = math.sqrt(sum(float(x) * float(x) for x in v))
    if s <= 0:
        return list(v)
    return [float(x) / s for x in v]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return sum(float(x) * float(y) for x, y in zip(a, b, strict=True))
