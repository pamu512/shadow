"""Pre-flight context injection for persona-specific mandatory reasoning steps."""
from __future__ import annotations

import json
import re
from pathlib import Path
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from backend.agent.state import AgentState
from backend.agent.tools_langchain import case_id_ctx, dataset_path_ctx, duckdb_path_ctx
from backend.tools.global_search import sample_entities_from_case_csv, search_historical_overlap
from backend.tools.bot_detector import detect_bot_clusters
from backend.tools.user_profiler import fetch_last_successful_login_sessions


_INVESTIGATE_TRIGGER = re.compile(r"\binvestigate\b", re.I)

_ELSEWHERE_TRIGGER = re.compile(
    r"\b(elsewhere|other\s+cases?|another\s+case|cross[-\s]?case|prior\s+cases?|previous\s+cases?|"
    r"appear(ed)?\s+(elsewhere|before|in\s+other)|did\s+.+\s+appear)\b",
    re.I,
)

_CROSS_REFERENCE_TRIGGER = re.compile(
    r"\b(cross[-\s]?reference|cross[-\s]?check|other\s+investigations?|another\s+dataset|different\s+case|"
    r"global\s+warehouse|compare\s+to\s+history|historical\s+cases?|link(ed)?\s+across\s+cases?)\b",
    re.I,
)

# Warehouse / hardware-hash / named trust users — stricter tool order than generic cross-case.
_WAREHOUSE_INTEL_TRIGGER = re.compile(
    r"\b(global\s+warehouse|search\s+the\s+warehouse|warehouse\b|canvas[_\s]?fingerprint|hardware\s+hash|"
    r"fingerprint|chargeback\s+case\s+logs?|TRUSTED_USER_[A-Z0-9_]+|canvas_hash_[A-Za-z0-9_]+)\b",
    re.I,
)

_HUMANOID_TRIGGER = re.compile(r"\bhumanoid\b", re.I)

_USER_ID_PATTERNS = (
    re.compile(r"\buser[_\s]*id[\s:=]+['\"]?([^\s'\",)]+)", re.I),
    re.compile(r"\b(?:for|user)\s+['\"]?([uU]_[a-zA-Z0-9_\-:.]+)['\"]?", re.I),
    re.compile(r"\b([uU]_[a-zA-Z0-9_]{4,})\b"),
    re.compile(r"\b(?:account|acct)[_\s]*id[\s:=]+['\"]?([^\s'\",)]+)", re.I),
)


def extract_candidate_user_id_from_messages(messages: list[BaseMessage]) -> str | None:
    """Best-effort user id from the latest human turns (ATO context injection)."""
    for m in reversed(messages):
        if not isinstance(m, HumanMessage):
            continue
        text = str(m.content or "")
        for rx in _USER_ID_PATTERNS:
            mm = rx.search(text)
            if mm:
                uid = mm.group(1).strip().strip("'\"")
                if uid:
                    return uid
    return None


def build_context_injection_messages(persona_id: str, messages: list[BaseMessage]) -> list[SystemMessage]:
    """Return system messages prepended after START (does not replace user content)."""
    pid = (persona_id or "").strip()
    out: list[SystemMessage] = []

    if pid == "ato_investigator":
        duck = duckdb_path_ctx.get()
        uid = extract_candidate_user_id_from_messages(messages)
        if duck and Path(duck).is_file() and uid:
            snap = fetch_last_successful_login_sessions(duck, uid, limit=10)
            out.append(
                SystemMessage(
                    content="[Context injection — last successful sessions]\n"
                    + json.dumps(snap, default=str)
                    + "\nCompare these rows to the current session before issuing an ATO verdict."
                )
            )
        elif duck and Path(duck).is_file():
            out.append(
                SystemMessage(
                    content=(
                        "[Context injection — ATO]\nDuckDB is available but no user_id was inferred from the "
                        "latest operator message. Prefer **analyze_ato_risk_tool** with **user_id=\"\"** so the server "
                        "auto-resolves acc_id/user_id from schema; or ask for one explicit id. "
                        "Do not stall on missing user_id when the dataset has a resolvable account column."
                    )
                )
            )

    if pid == "bot_hunter":
        out.insert(
            0,
            SystemMessage(
                content=(
                    "[Bot Hunter — schema gate & retry protocol]\n"
                    "Before **detect_bot_clusters_tool** in your reply, you MUST call **get_dataset_schema** OR "
                    "**execute_in_sandbox** (e.g. Polars `read_csv(...).head(5)`) on the active CSV—no guessing headers.\n"
                    "Map: **user_id** ➔ acc_id / uid / customer_id; **created_at** ➔ timestamp / date / signup_time; "
                    "**canvas_fingerprint** ➔ browser_hash / fingerprint_id / fingerprint.\n"
                    "**Silent recovery:** If detection is incomplete, follow the Bot Hunter system prompt (schema + "
                    "mapped columns + retry); do not dump raw need-column errors to the operator.\n"
                    "**No placeholders:** Never `[insert date]`—if tools failed, quote the exact `error` from JSON."
                ),
            ),
        )
        path = dataset_path_ctx.get()
        if path and Path(path).is_file():
            try:
                d = detect_bot_clusters(path)
            except Exception as exc:  # noqa: BLE001
                d = {"ok": False, "error": str(exc), "bot_density_pct": None}
            density = d.get("bot_density_pct")
            row_count = d.get("row_count")
            clusters = d.get("clusters") if isinstance(d.get("clusters"), list) else []
            n_clusters = len(clusters)
            manual = None
            if isinstance(density, (int, float)):
                manual = max(0.0, min(100.0, 100.0 - float(density)))
            out.append(
                SystemMessage(
                    content=(
                        "[Context injection — bot density preview (server)]\n"
                        + json.dumps(
                            {
                                "bot_density_pct": density,
                                "row_count": row_count,
                                "cluster_count": n_clusters,
                                "manual_like_registration_pct": manual,
                                "ok": d.get("ok", True),
                                "error": d.get("error"),
                            },
                            default=str,
                        )
                        + "\nThis is a **preview only**—still run **get_dataset_schema** or **execute_in_sandbox** "
                        "then **detect_bot_clusters_tool** in your tool chain. If preview shows `ok: false`, follow "
                        "**Retry or die**: no operator summary until your own tool call succeeds."
                    )
                )
            )
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and _INVESTIGATE_TRIGGER.search(str(m.content or "")):
                out.append(
                    SystemMessage(
                        content=(
                            "[Investigate — aggregate first]\n"
                            "Run **execute_in_sandbox** with Polars on the active CSV: `group_by(canvas_fingerprint)` "
                            "(or the canvas column from **get_dataset_schema**) with row counts and `n_unique` on the "
                            "IP column — same idea as `SELECT canvas_fingerprint, COUNT(*), COUNT(DISTINCT ip) ... GROUP BY 1`. "
                            "If one fingerprint accounts for ~100% of rows while IPs stay unique, report **High-Confidence "
                            "Hardware Spoofing Ring** using numbers from stdout or **detect_bot_clusters_tool** fields "
                            "`hardware_spoofing_assessment` / `canvas_fingerprint_distribution`. Do not invent Gmail/email "
                            "patterns unless an email column exists in the schema."
                        ),
                    ),
                )
                break

    if pid == "fraud_ring_detective":
        out.append(
            SystemMessage(
                content=(
                    "[Context injection — multi-hop]\n"
                    "Before naming kingpins, verify ≥3-hop linkage narratives using find_fraud_rings_tool output: "
                    "Account → shared IP/device/address/phone → other Account → device or payer/payee edge. "
                    "Use linkage_alerts, cycles, and multi_hop_scan from tool JSON."
                )
            )
        )

    cid = case_id_ctx.get()
    dsp = dataset_path_ctx.get()
    if cid and dsp and Path(dsp).is_file():
        samples = sample_entities_from_case_csv(dsp)
        overlaps: list = []
        for et, val in list(samples.items())[:3]:
            rep = search_historical_overlap(val, et, exclude_case_id=cid)
            if rep.get("other_cases"):
                overlaps.append(rep)
        if overlaps:
            out.append(
                SystemMessage(
                    content="[Global warehouse — automatic historical overlap]\n"
                    + json.dumps({"overlaps": overlaps}, default=str)
                    + "\nYou MUST still call search_historical_overlap_tool for any additional suspect entities before a final verdict."
                )
            )
        else:
            out.append(
                SystemMessage(
                    content=(
                        "[Global warehouse] Sampled early CSV rows show no indexed cross-case hits yet. "
                        "Call search_historical_overlap_tool for suspect IPs, user_ids, devices, and card hashes before finalizing."
                    )
                )
            )

    if pid == "general":
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                t = str(m.content or "")
                if _HUMANOID_TRIGGER.search(t):
                    out.insert(
                        0,
                        SystemMessage(
                            content=(
                                "[Mandatory tool order — Humanoid stress test]\n"
                                "Do **not** ask the operator for the Humanoid dataset. Call "
                                "**humanoid_stress_test_linkage_tool** immediately (warehouse probe for stress IP "
                                "**1.1.1.1** + canvas/device alignment vs this case). Then **search_historical_overlap_tool** "
                                "for any additional entities. If the tool JSON includes `required_narrative`, you MUST "
                                "include that exact sentence in your answer."
                            ),
                        ),
                    )
                    break
                if _WAREHOUSE_INTEL_TRIGGER.search(t):
                    out.insert(
                        0,
                        SystemMessage(
                            content=(
                                "[Mandatory tool order — warehouse / hardware / trust users]\n"
                                "Call **warehouse_search_text_tool** with the exact canvas/hardware hash string and again "
                                "with any named user id (e.g. TRUSTED_USER_001). "
                                "Call **search_historical_overlap_tool** with entity_type **device_id** and entity_id = "
                                "the full canvas fingerprint / hash (warehouse indexes fingerprints as device-class "
                                "entities); use **user_id** only for real account identifiers.\n"
                                "Do **not** answer cross-case questions from **get_dataset_schema** alone. Do **not** "
                                "claim Chargeback log hits, velocity bundles, or links to trusted users unless the "
                                "**warehouse_** or **search_historical_overlap_** tool JSON explicitly shows them.\n"
                                "Never put JSON tool DSL or fake `name/parameters` objects inside a Python code fence—"
                                "only real **execute_in_sandbox** Python."
                            ),
                        ),
                    )
                    break
                if _ELSEWHERE_TRIGGER.search(t) or _CROSS_REFERENCE_TRIGGER.search(t):
                    out.insert(
                        0,
                        SystemMessage(
                            content=(
                                "[Mandatory tool order — cross-case / global]\n"
                                "You are **forbidden** from asking for files or permission. The data is assumed to exist "
                                "in GlobalWarehouse. First call **search_historical_overlap_tool** for each inferable "
                                "`user_id`, `ip_address`, `device_id`, and `card_hash`, and/or **warehouse_query_tool** / "
                                "**warehouse_search_text_tool** targeting `source_case_id` and `row_json`—before "
                                "**get_dataset_schema** unless the question is strictly local column definitions."
                            ),
                        ),
                    )
                    break
                break

    return out


def context_injection_node(persona_id: str):
    """LangGraph node factory: prepend mandatory reasoning context."""

    def _node(state: AgentState) -> dict:
        extras = build_context_injection_messages(persona_id, state["messages"])
        if not extras:
            return {}
        return {"messages": list(extras)}

    return _node
