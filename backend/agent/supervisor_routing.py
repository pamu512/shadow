"""Robust supervisor routing: structured LLM output with retries + semantic + keyword fallbacks."""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Literal

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.llm_preferences import effective_ollama_model

logger = logging.getLogger("backend.agent.supervisor")

AgentName = Literal["code_agent", "ml_agent", "analyst"]

# Short prototype strings per route for embedding similarity (Ollama /api/embeddings).
_SEMANTIC_PROTOTYPES: dict[AgentName, tuple[str, ...]] = {
    "ml_agent": (
        "train isolation forest or random forest fraud model threshold optimization",
        "XGBoost gradient boosting classifier labels supervised learning",
        "feature importance fraud score calibration precision recall",
        "unsupervised anomaly detection bot score",
    ),
    "code_agent": (
        "run polars pandas python script on csv execute sandbox",
        "R tidyverse data.table ggplot analysis",
        "review refactor this python or r code",
        "generate scaffold sql window function",
    ),
    "analyst": (
        "investigate this user chargeback friendly fraud narrative",
        "account takeover session risk behavioral profile",
        "fraud ring graph louvain bot cluster hardware fingerprint",
        "warehouse historical overlap recidivist",
        "who owns this ip address asn isp which organization registered that ip",
    ),
}

_CACHED_PROTOTYPE_EMBEDDINGS: dict[AgentName, list[list[float]]] = {}
_CACHE_LOCK = __import__("threading").Lock()


def _get_cached_prototype_embeddings() -> dict[AgentName, list[list[float]]]:
    global _CACHED_PROTOTYPE_EMBEDDINGS
    with _CACHE_LOCK:
        if _CACHED_PROTOTYPE_EMBEDDINGS:
            return _CACHED_PROTOTYPE_EMBEDDINGS

        # Build cache
        for agent, protos in _SEMANTIC_PROTOTYPES.items():
            embs = _embed_texts(list(protos))
            if embs:
                _CACHED_PROTOTYPE_EMBEDDINGS[agent] = [_l2_normalize(e) for e in embs]

        return _CACHED_PROTOTYPE_EMBEDDINGS


def _ollama_embeddings_base() -> str:
    """Ollama native API base (strip /v1 OpenAI-compat suffix)."""
    u = (settings.ollama_base_url or "").strip().rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3]
    return u or "http://localhost:11434"


def _embed_texts(texts: list[str], *, timeout: float = 60.0) -> list[list[float]] | None:
    """Call Ollama /api/embeddings for each string; return None on total failure."""
    if not texts:
        return []
    model = effective_ollama_model()
    base = _ollama_embeddings_base()
    url = f"{base}/api/embeddings"
    out: list[list[float]] = []
    try:
        with httpx.Client(timeout=timeout) as client:
            for t in texts:
                r = client.post(url, json={"model": model, "prompt": t[:8000]})
                if r.status_code != 200:
                    logger.warning("embeddings HTTP %s: %s", r.status_code, r.text[:200])
                    return None
                data = r.json()
                emb = data.get("embedding")
                if not isinstance(emb, list) or not emb:
                    return None
                out.append([float(x) for x in emb])
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("embeddings failed: %s", exc)
        return None


def _l2_normalize(v: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in v))
    if s <= 0:
        return v
    return [x / s for x in v]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


def semantic_route_fallback(user_text: str) -> AgentName:
    """Pick specialist by max cosine similarity to prototype embeddings."""
    q = (user_text or "").strip() or "investigate"
    q_emb = _embed_texts([q])
    if not q_emb:
        return _keyword_route_fallback(user_text)
    qv = _l2_normalize(q_emb[0])

    cached_protos = _get_cached_prototype_embeddings()
    if not cached_protos:
        return _keyword_route_fallback(user_text)

    best: AgentName = "analyst"
    best_score = -1.0
    for agent, proto_embs in cached_protos.items():
        scores = [_cosine(qv, pe) for pe in proto_embs]
        mx = max(scores) if scores else -1.0
        if mx > best_score:
            best_score = mx
            best = agent
    if best_score < 0.15:
        return _keyword_route_fallback(user_text)
    return best


def _keyword_route_fallback(text: str) -> AgentName:
    t = text.lower()
    if any(
        k in t
        for k in (
            "threshold",
            "xgboost",
            "isolation",
            "forest",
            "fraud score",
            "train model",
            "classifier",
            "precision",
            "recall",
            "feature importance",
        )
    ):
        return "ml_agent"
    if any(
        k in t
        for k in (
            "polars",
            "pandas",
            "rscript",
            "data.table",
            "review code",
            "python",
            "execute",
            "ggplot",
            "scaffold",
        )
    ):
        return "code_agent"
    return "analyst"


def invoke_supervisor_route(
    llm: Any,
    *,
    supervisor_prompt: str,
    last_user: str,
    max_attempts: int = 3,
) -> AgentName:
    """Structured routing with retries; then semantic embedding router; then keywords."""
    from pydantic import BaseModel, Field

    class SupervisorRoute(BaseModel):
        next_agent: Literal["code_agent", "ml_agent", "analyst"] = Field(
            description="Which specialist should answer the user request"
        )

    structured = llm.with_structured_output(SupervisorRoute)
    last_err: str | None = None
    for attempt in range(max_attempts):
        try:
            decision = structured.invoke(
                [
                    SystemMessage(content=supervisor_prompt),
                    HumanMessage(content=last_user or "Hello"),
                ]
            )
            return decision.next_agent
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            logger.info(
                "supervisor structured output attempt %s/%s failed: %s",
                attempt + 1,
                max_attempts,
                last_err[:300],
            )
            time.sleep(0.08 * (attempt + 1))
    logger.warning("supervisor falling back after retries: %s", last_err)
    return semantic_route_fallback(last_user)
