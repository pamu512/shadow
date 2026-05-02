"""Persona resolution, schema-aware suggestions, and prompt assembly for the agent graph."""
from __future__ import annotations

import re
from typing import Any

from backend.agent.personas import DEFAULT_PERSONA_ID, Persona, get_persona


def _normalize_col(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    return s


def extract_column_names(schema_summary: dict[str, Any] | None) -> set[str]:
    """Column names from a case `schema_summary` payload (DuckDB ingestion shape)."""
    if not schema_summary or not isinstance(schema_summary, dict):
        return set()
    cols = schema_summary.get("columns")
    if not isinstance(cols, list):
        return set()
    out: set[str] = set()
    for c in cols:
        if isinstance(c, dict) and c.get("name"):
            out.add(_normalize_col(str(c["name"])))
    return out


# persona_id -> keywords matched as substrings of normalized column names
_PERSONA_DETECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "chargeback_specialist": (
        "chargeback",
        "dispute",
        "reason_code",
        "chargeback_date",
        "dispute_reason",
        "arn",
        "representment",
        "cbk",
        "issuer_reason",
        "ethoca",
        "verifi",
        "pre_arbitration",
    ),
    "ato_investigator": (
        "account_takeover",
        "ato",
        "impossible_travel",
        "new_device",
        "device_fingerprint",
        "credential",
        "password_reset",
        "mfa",
        "step_up",
        "session",
        "sim_swap",
        "recovery_email",
    ),
    "bot_hunter": (
        "user_agent",
        "bot_score",
        "headless",
        "tls",
        "ja3",
        "automation",
        "fingerprint",
        "mouse",
        "keystroke",
        "crawler",
    ),
    "promo_abuse_agent": (
        "promo",
        "coupon",
        "referral",
        "voucher",
        "signup_bonus",
        "discount_code",
        "multi_account",
        "sybil",
    ),
    "fraud_ring_detective": (
        "network_id",
        "graph_cluster",
        "ring",
        "mule",
        "shared_device",
        "community_id",
        "connected_component",
        "reship",
    ),
    "collusion_expert": (
        "collusion",
        "counterparty",
        "buyer_id",
        "seller_id",
        "bid_rigging",
        "shill",
        "marketplace",
        "merchant_id",
    ),
}


def suggest_persona_from_columns(columns: set[str]) -> tuple[str, list[str]] | None:
    """
    Auto-detect a recommended persona from dataset columns.
    Returns (persona_id, matching_column_names) or None if no strong signal.
    """
    if not columns:
        return None
    col_list = sorted(columns)
    best_pid: str | None = None
    best_hits: list[str] = []
    best_score = 0
    for pid, keywords in _PERSONA_DETECTION_KEYWORDS.items():
        hits: list[str] = []
        for col in col_list:
            if any(kw in col for kw in keywords):
                hits.append(col)
        score = len(set(hits))
        if score > best_score:
            best_score = score
            best_pid = pid
            best_hits = hits
    if best_score == 0 or best_pid is None:
        return None
    return (best_pid, best_hits)


def suggest_persona_from_schema(schema_summary: dict[str, Any] | None) -> tuple[str, list[str]] | None:
    return suggest_persona_from_columns(extract_column_names(schema_summary))


def resolve_persona_id(persona_id: str | None) -> str:
    """Normalize request persona id; unknown ids fall back to default."""
    pid = (persona_id or DEFAULT_PERSONA_ID).strip()
    p = get_persona(pid)
    return p.id


def analyst_react_instructions() -> str:
    return (
        "You are a fraud analytics analyst. Be concise. "
        "When you identify actionable fraud hypotheses, call emit_lead with a severity score, "
        "clear description, and a JSON raw_data_snippet string. "
        "Use get_dataset_schema when you need column context."
    )


def build_analyst_system_prompt(persona: Persona) -> str:
    """Full analyst-facing system content for the ReAct agent."""
    tools_hint = ", ".join(persona.recommended_tools[:8])
    return (
        f"{persona.system_prompt}\n\n"
        f"Lens: {persona.display_name}. Preferred analytic modules (stub/registry): {tools_hint}.\n"
        f"{analyst_react_instructions()}"
    )


def build_code_agent_prompt(persona: Persona) -> str:
    return (
        f"You are a code and sandbox specialist for local fraud analytics. "
        f"Investigator lens: {persona.display_name}. "
        f"Help with Polars, R, review, scaffold, and sandbox execution. Be concise."
    )


def build_ml_agent_prompt(persona: Persona) -> str:
    return (
        f"You are an ML and thresholds specialist. Investigator lens: {persona.display_name}. "
        f"Handle isolation forest, random forest, anomaly scoring, and threshold tuning. Be concise."
    )


def build_supervisor_context(persona: Persona) -> str:
    return (
        "Route user requests for Shadow (local fraud analytics workspace). "
        f"Active specialist lens: {persona.display_name}. "
        "code_agent: code review, scaffolding, sandbox execution. "
        "ml_agent: threshold tuning, sklearn, anomaly detection. "
        "analyst: general questions, synthesis, and evidence-friendly narratives."
    )


def build_persona_suggestion(schema_summary: dict[str, Any] | None):
    """Build API payload when dataset columns imply a specialist lens."""
    from backend.schemas import PersonaSuggestionOut

    tup = suggest_persona_from_schema(schema_summary)
    if not tup:
        return None
    pid, cols = tup
    p = get_persona(pid)
    sample = ", ".join(sorted(set(cols))[:6])
    suffix = f" Example signals: {sample}." if sample else ""
    return PersonaSuggestionOut(
        persona_id=pid,
        display_name=p.display_name,
        reason=f"Auto-detect: schema matches {p.display_name} indicators.{suffix}",
        matching_columns=sorted(set(cols))[:32],
    )

