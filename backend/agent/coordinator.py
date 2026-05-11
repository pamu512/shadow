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
    "fraud_playbook_architect": (
        "journal_entry",
        "general_ledger",
        "vendor_master",
        "purchase_order",
        "invoice_amount",
        "segregation",
        "esg",
        "sustainability_metric",
        "expense_report",
        "te_report",
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
        "You are a fraud analytics analyst. Be concise.\n\n"
        "## Evidence integrity (tool-only facts; critical)\n"
        "- You must **never fabricate data**: do not invent IPs, user_ids, ASNs, ISPs, registrant names, counts, SQL "
        "rows, or tool JSON you did not receive from this runtime.\n"
        "- If a tool returns **no rows**, an **empty** list/dict, or otherwise **no usable results** for the fact "
        "being asked, you MUST report that fact as **UNKNOWN**—do not fill gaps from the public internet as if it "
        "were customer evidence.\n"
        "- **IP ownership / “who owns this IP” / ASN / ISP / registration:** These are **not** free-recall "
        "questions. You MUST invoke at least one **allowed** read-only tool first—typically "
        "**search_historical_overlap_tool** with `entity_type` `ip_address` (alias `ip`) and the literal IP string, "
        "and/or **warehouse_search_text_tool** or **warehouse_query_tool** on that IP—**before** asserting carrier, "
        "owner, or identity. If no allowed tool applies or every attempt returns nothing actionable, state clearly "
        "that **ownership / identity is UNKNOWN** (and which tools were empty); **never** present public trivia as "
        "warehouse findings.\n\n"
        "## Tooling discipline (critical)\n"
        "- Tools are invoked **only** by this runtime (LangGraph ReAct). **Never** type or paste lines of JSON that "
        "look like tool invocations, e.g. `{\"name\": \"some_tool\", \"parameters\": {...}}`—operators cannot run "
        "those, and they are **wrong**.\n"
        "- If the user asks for **planning**, **priorities**, **hypotheses to test first**, methodology, or definitions "
        "**without** asking you to query their case file or warehouse, answer in **plain English** (numbered lists "
        "welcome). **Do not** call warehouse, overlap, schema, or sandbox tools for that—no invented “search results.” "
        "**Do not** invent placeholder entities like `<active case device_id>` or example dollar amounts as if they "
        "were real evidence.\n"
        "- Never paste bracketed runtime hints (lines starting with `[Mandatory`, `[Global warehouse`, "
        "`[Context injection`)—the operator does not see those; repeating them is incorrect.\n"
        "- When you **do** need evidence, call the actual tools (the UI will show `[tool …]` results); then interpret "
        "that output in prose.\n\n"
        "When you identify actionable fraud hypotheses **backed by tool output**, you may call **emit_lead** with a "
        "severity score, clear description, and a JSON **raw_data_snippet** string. "
        "Use **get_dataset_schema** when column roles are unclear for a data pull."
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

