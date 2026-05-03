"""LLM-based tool output confidence (replaces brittle static heuristics)."""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger("backend.agent.tool_confidence")

_MAX_CACHE = 256
_cache: OrderedDict[tuple[str, str], float] = OrderedDict()


class ToolConfidenceOut(BaseModel):
    confidence_score: float = Field(ge=0.0, le=1.0, description="0 weak, 1 decisive")
    rationale: str = Field(default="", max_length=160)


def _deterministic_confidence(payload: dict[str, Any], tool_name: str) -> float:
    """Fast heuristic scoring (<1ms) for RFI / UI when LLM scoring is off."""
    if isinstance(payload.get("confidence_score"), (int, float)):
        return max(0.0, min(1.0, float(payload["confidence_score"])))
    if payload.get("ok") is False:
        return 0.28
    if payload.get("error"):
        return 0.26
    score = 0.52
    if payload.get("ok") is True:
        score = 0.62
    rc = payload.get("row_count")
    if isinstance(rc, int):
        if rc <= 0:
            score -= 0.12
        elif rc >= 200:
            score += 0.08
        elif rc >= 50:
            score += 0.04
    if isinstance(payload.get("truncated"), bool) and payload["truncated"]:
        score += 0.03
    # Tool-specific boosts (deterministic, no model)
    tl = (tool_name or "").lower()
    if "warehouse" in tl or "overlap" in tl:
        hits = payload.get("global_hits")
        if hits is True:
            score += 0.1
        elif hits is False and payload.get("distinct_case_count") == 0:
            score -= 0.05
    if "chargeback" in tl or "ato" in tl or "fraud" in tl:
        sev = payload.get("severity") or payload.get("risk_tier")
        if isinstance(sev, str) and sev.upper() in ("HIGH", "CRITICAL", "SEVERE"):
            score += 0.12
    return max(0.0, min(1.0, score))


def _cache_get(key: tuple[str, str]) -> float | None:
    val = _cache.pop(key, None)
    if val is not None:
        _cache[key] = val
    return val


def _cache_set(key: tuple[str, str], score: float) -> None:
    if key in _cache:
        _cache.pop(key, None)
    _cache[key] = score
    while len(_cache) > _MAX_CACHE:
        _cache.popitem(last=False)


def infer_tool_confidence_score(
    llm: "BaseChatModel",
    tool_name: str,
    payload: dict[str, Any],
) -> float:
    """Return a calibrated confidence in [0,1] for RFI / UI enrichment."""
    if isinstance(payload.get("confidence_score"), (int, float)):
        return max(0.0, min(1.0, float(payload["confidence_score"])))

    body = json.dumps(payload, sort_keys=True, default=str)[:8000]
    cache_key = (tool_name, body)
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit

    if not settings.llm_tool_confidence:
        out = _deterministic_confidence(payload, tool_name)
        _cache_set(cache_key, out)
        return out

    structured = llm.with_structured_output(ToolConfidenceOut)
    sys = SystemMessage(
        content=(
            "You score how well this fraud-analytics tool JSON supports a decisive analyst conclusion. "
            "Use 0.0–0.35 for failures, sparse data, or contradictory signals; 0.5–0.7 for moderate evidence; "
            "0.75–1.0 only for strong, internally consistent metrics. Be conservative."
        )
    )
    human = HumanMessage(content=f"Tool name: {tool_name}\nPayload:\n{body}")
    try:
        parsed = structured.invoke([sys, human])
        score = max(0.0, min(1.0, float(parsed.confidence_score)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool confidence LLM failed for %s: %s", tool_name, exc)
        score = _deterministic_confidence(payload, tool_name)
    _cache_set(cache_key, score)
    return score
