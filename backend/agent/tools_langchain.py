"""LangChain tools wrapping backend capabilities."""
from __future__ import annotations

import contextvars
import json
from typing import Literal

from langchain_core.tools import tool

from backend.agents.registry import get_fraud_agent
from backend.database import new_lead_id
from backend.database.models import Lead
from backend.realtime.evidence_hub import push_lead_event
from backend.database.session import SessionLocal
from backend.schemas import LeadOut
from backend.tools.ato_analyzer import analyze_ato_risk, infer_user_id_from_duckdb
from backend.tools.bot_detector import detect_bot_clusters
from backend.tools.bulk_manager import batch_flag_accounts
from backend.tools.chargeback_analyzer import analyze_chargeback_risk
from backend.tools.chargeback_trust_velocity import trust_velocity_forensic_scan
from backend.tools.code_review_lib import review_script
from backend.tools.dataset_schema import describe_csv
from backend.tools.evidence_builder import build_representment_manifest
from backend.tools.representment_simulation import simulate_issuer_representment_review
from backend.tools.optimize_thresholds import run_optimize
from backend.tools.network_analyzer import find_fraud_rings
from backend.tools.ring_profiler import summarize_roles
from backend.tools.sandbox_exec import execute_code
from backend.tools.scaffold_code import generate_scaffold
from backend.tools.global_search import search_historical_overlap as run_search_historical_overlap
from backend.tools.user_profiler import build_user_behavioral_profile
from backend.tools.humanoid_linkage import run_humanoid_stress_test_linkage
from backend.tools.warehouse_query import run_warehouse_query, run_warehouse_text_search

from .ollama import get_llm
from .tool_self_heal import mentions_missing_user_identifier, rank_user_column_candidates, strip_traceback_for_agent_ui

case_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("case_id", default=None)
dataset_path_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("dataset_path", default=None)
duckdb_path_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("duckdb_path", default=None)


def set_agent_context(
    *,
    case_id: str | None,
    dataset_path: str | None,
    duckdb_path: str | None = None,
) -> None:
    case_id_ctx.set(case_id)
    dataset_path_ctx.set(dataset_path)
    duckdb_path_ctx.set(duckdb_path)


@tool
def get_dataset_schema() -> str:
    """Return CSV schema description for the active dataset path."""
    path = dataset_path_ctx.get()
    if not path:
        return "No dataset path in context."
    return str(describe_csv(path))


@tool
def review_script_tool(script: str, language: Literal["python", "r"]) -> str:
    """Review and optimize a Python or R script against the active dataset schema."""
    _orig, suggested, notes = review_script(script, language, dataset_path_ctx.get(), llm=get_llm())
    return f"{notes}\n\n```\n{suggested}\n```"


@tool
def scaffold_code_tool(language: Literal["python", "r"], intent: str) -> str:
    """Generate Polars or data.table scaffold code."""
    code, explanation = generate_scaffold(language, intent)
    return f"{explanation}\n\n```\n{code}\n```"


@tool
def execute_in_sandbox(language: Literal["python", "r"], code: str) -> str:
    """Execute Python or R inside the workspace sandbox. Python may **import polars, pandas, numpy, matplotlib**, and
    other allowlisted stdlib-style modules (see sandbox policy). For Bot Hunter, prefer **Polars** or **pandas** on the
    active CSV path from context for GROUP BY / value_counts. For **matplotlib**, `MPLBACKEND=Agg` is set; to return a
    plot to the UI, call **`plt.savefig(os.path.join(PLOT_DIR, 'out.png'))`** — `PLOT_DIR` is injected at the top of the
    script (same as env `FRAUD_PLOT_DIR`). `plt.show()` alone may not emit a captured image. Summarize printed stdout
    only—do not invent metrics."""
    out = execute_code(language, code, timeout_sec=120)
    plots = len(out.get("plots_base64") or [])
    violations = out.get("violations") or []
    v = "\n".join(violations) if violations else ""
    body = (
        f"exit={out['exit_code']}\nstdout:\n{out['stdout']}\nstderr:\n{out['stderr']}\n"
        f"plots={plots}\nviolations:\n{v}"
    )
    path = dataset_path_ctx.get()
    if path and mentions_missing_user_identifier(body):
        body = strip_traceback_for_agent_ui(body)
        try:
            sch = str(describe_csv(path))
        except Exception as exc:  # noqa: BLE001
            sch = f"(schema unavailable: {exc})"
        body = (
            f"{body}\n\n---\n[self_heal] Dataset schema attached because output referenced a missing user/account "
            f"column. Re-run using one of the real column names below:\n{sch}"
        )
    elif "traceback" in body.lower():
        body = strip_traceback_for_agent_ui(body)
    return body


@tool
def optimize_thresholds_tool(
    model: Literal["isolation_forest", "random_forest"] = "isolation_forest",
    target_column: str | None = None,
) -> str:
    """Train sklearn model and return threshold manifest for the active dataset."""
    path = dataset_path_ctx.get()
    if not path:
        return "No dataset path configured for this case."
    result = run_optimize(path, model, target_column, None)
    return str(result)


@tool
def emit_lead(severity: float, description: str, raw_data_snippet: str) -> str:
    """Record a fraud lead on the Evidence Board (investigator UI).

    Use when you identify a suspicious pattern, anomaly, or risk signal worth triage.
    severity: 0.0–1.0 (higher = more severe).
    description: Short hypothesis for investigators (what is wrong / why it matters).
    raw_data_snippet: JSON string of the triggering row(s), aggregates, or feature snapshot.

    Leads appear in the workspace Evidence Board and in the **Active Leads** sidebar while a case is selected;
    connected WebSocket clients receive `lead_created` immediately.
    """
    cid = case_id_ctx.get()
    if not cid:
        return "No active case in context; ask the operator to select a case, then emit again."

    sev = float(severity)
    sev = max(0.0, min(1.0, sev))

    import json

    raw_data: dict | None
    try:
        parsed = json.loads(raw_data_snippet)
        if isinstance(parsed, dict):
            raw_data = parsed
        else:
            raw_data = {"value": parsed}
    except json.JSONDecodeError:
        raw_data = {"snippet": raw_data_snippet}

    db = SessionLocal()
    try:
        lid = new_lead_id()
        lead = Lead(
            id=lid,
            case_id=cid,
            description=description.strip() or "Unspecified pattern",
            severity_score=sev,
            raw_data_ref=raw_data,
            status="OPEN",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        payload = LeadOut.model_validate(lead).model_dump(mode="json")
        push_lead_event(cid, {"type": "lead_created", "lead": payload})
        return f"Lead {lid} emitted to Evidence Board (severity={sev:.2f})."
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return f"Failed to emit lead: {exc}"
    finally:
        db.close()


def build_code_tools() -> list:
    return [get_dataset_schema, review_script_tool, scaffold_code_tool, execute_in_sandbox, emit_lead]


def build_ml_tools() -> list:
    return [get_dataset_schema, optimize_thresholds_tool, execute_in_sandbox, emit_lead]


@tool
def chargeback_trust_velocity_tool(
    target_amount: float = 0.0,
    transaction_id: str = "",
) -> str:
    """PROACTIVE Trust vs. Velocity scan on the active case CSV: isolates disputed/focal row, counts prior
    completed orders for the same user, compares average historical amount to the focal amount, checks IP/device
    reuse vs warm-up, and labels **Potential Account Seasoning for Friendly Fraud** when focal >10× average with
    enough prior completed rows. Call immediately after get_dataset_schema when the operator asks about a specific
    transaction or genuineness (do not ask for raw snippets if the CSV is in context). Returns JSON with
    kind=forensic_verdict_card for the Forensic Verdict Card UI."""
    path = dataset_path_ctx.get()
    if not path:
        return json.dumps({"ok": False, "error": "No dataset path in context.", "kind": "forensic_verdict_card"})
    ta = float(target_amount) if target_amount else None
    if ta is not None and ta <= 0:
        ta = None
    tid = (transaction_id or "").strip() or None
    return json.dumps(
        trust_velocity_forensic_scan(path, target_amount=ta, transaction_id=tid),
        default=str,
    )


@tool
def analyze_chargeback_risk_tool() -> str:
    """Analyze the active case's transaction CSV for friendly-fraud signals: IP/device match to prior
    undisputed activity, logins or digital access after dispute date, 3+ disputes in 6 months,
    billing vs shipping mismatch, and strong AVS/CVV. Returns JSON with chargeback_risk_score,
    win_probability, and executive_summary bullet points to cite in plain English."""
    path = dataset_path_ctx.get()
    if not path:
        return json.dumps({"ok": False, "error": "No dataset path in context. Select a case with a CSV."})
    return json.dumps(analyze_chargeback_risk(path), default=str)


@tool
def build_representment_manifest_tool(transaction_id: str) -> str:
    """Build a Representment Manifest (JSON) for a transaction_id: proof of service (IP, login,
    digital access), proof of delivery (tracking fields), policy acknowledgment (ToS fields),
    AVS/CVV, communications. Use after analyzing risk; quote specific fields in your narrative."""
    path = dataset_path_ctx.get()
    if not path:
        return json.dumps({"ok": False, "error": "No dataset path in context."})
    tid = (transaction_id or "").strip()
    if not tid:
        return json.dumps({"ok": False, "error": "transaction_id required."})
    return json.dumps(build_representment_manifest(tid, path), default=str)


@tool
def simulate_representment_tool(transaction_id: str = "") -> str:
    """Simulate how an Issuing Bank analyst would view representment evidence. Uses the case CSV:
    runs the automated friendly-fraud scan and, if transaction_id is non-empty, attaches the
    representment manifest for that order. Returns JSON with issuer_perspective_memo (bank voice:
    strengths, gaps, likely outcome). Use when the merchant asks 'would we win?' or wants a bank-side drill."""
    path = dataset_path_ctx.get()
    if not path:
        return json.dumps({"ok": False, "error": "No dataset path in context. Select a case with a CSV."})
    tid = (transaction_id or "").strip() or None
    return json.dumps(simulate_issuer_representment_review(path, transaction_id=tid), default=str)


def _build_user_behavioral_profile_payload(
    p: str,
    uid: str,
    *,
    user_column: str | None,
    table: str = "dataset",
) -> dict:
    return build_user_behavioral_profile(p, uid, user_column=user_column, table=table)


@tool
def build_user_behavioral_profile_tool(user_id: str, user_column: str = "") -> str:
    """Build Behavioral DNA from DuckDB history: login-hour patterns, top user agents, screen sizes,
    ISPs, geo hotspots, avg amounts, trusted device IDs. Requires an ingested case DuckDB."""
    p = duckdb_path_ctx.get()
    if not p:
        return json.dumps(
            {"ok": False, "error": "No DuckDB in context; upload a CSV so the case gets an analytical store."},
        )
    uid = (user_id or "").strip()
    uc = (user_column or "").strip() or None

    if not uid:
        inferred_uid, inferred_uc, meta = infer_user_id_from_duckdb(p, user_column=uc, table="dataset")
        if inferred_uid:
            payload = _build_user_behavioral_profile_payload(p, inferred_uid, user_column=inferred_uc or uc)
            if payload.get("ok"):
                payload["self_heal"] = {"inferred_user_id": True, "user_column_used": inferred_uc or uc}
                return json.dumps(payload, default=str)
        err = meta.get("error", "user_id required.") if isinstance(meta, dict) else "user_id required."
        return json.dumps({"ok": False, "error": err, **{k: v for k, v in (meta or {}).items() if k != "error"}}, default=str)

    payload = _build_user_behavioral_profile_payload(p, uid, user_column=uc)
    if payload.get("ok") is not False:
        return json.dumps(payload, default=str)

    err = str(payload.get("error") or "")
    avail = payload.get("available_columns")
    if isinstance(avail, list) and avail and "could not resolve user id column" in err.lower():
        tried: list[str] = []
        if uc:
            tried.append(uc)
        for cand in rank_user_column_candidates(str(x) for x in avail):
            if cand in tried:
                continue
            tried.append(cand)
            retry = _build_user_behavioral_profile_payload(p, uid, user_column=cand)
            if retry.get("ok"):
                retry["self_heal"] = {"retried_user_column": cand, "schema_auto_mapped": True}
                return json.dumps(retry, default=str)

    return json.dumps(payload, default=str)


@tool
def batch_flag_bot_cluster_tool(account_ids_json: str, reason: str, cluster_id: str = "") -> str:
    """Batch-flag or queue suspension for many synthetic accounts. Pass account_ids_json as a JSON array
    of string ids (e.g. ['u1','u2']). Reason is stored on the audit trail. Optional cluster_id ties back to
    detect_bot_clusters output."""
    cid = case_id_ctx.get()
    if not cid:
        return json.dumps({"ok": False, "error": "No active case in context."})
    try:
        parsed = json.loads(account_ids_json or "[]")
    except json.JSONDecodeError as exc:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {exc}"})
    if not isinstance(parsed, list):
        return json.dumps({"ok": False, "error": "account_ids_json must be a JSON array."})
    ids = [str(x).strip() for x in parsed if str(x).strip()]
    if not ids:
        return json.dumps(
            {
                "ok": True,
                "skipped": True,
                "flagged_count": 0,
                "cluster_id": (cluster_id or "").strip() or None,
                "message": "No account ids in array; nothing flagged.",
                "account_ids": [],
                "clusters": [],
            },
            default=str,
        )
    db = SessionLocal()
    try:
        out = batch_flag_accounts(
            db,
            case_id=cid,
            account_ids=ids,
            reason=(reason or "BOT_CLUSTER").strip(),
            cluster_id=(cluster_id or "").strip() or None,
            action_code="BULK_BOT_FLAG",
            agent_notes="Agent batch_flag_bot_cluster_tool invocation.",
        )
        return json.dumps(out, default=str)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)})
    finally:
        db.close()


def _peek_dataset_columns(dataset_path: str) -> list[str]:
    """Best-effort CSV headers for error envelopes (does not run full detection)."""
    try:
        import polars as pl

        return list(pl.read_csv(dataset_path, n_rows=1).columns)
    except Exception:
        return []


def _columns_found_from_detector(out: dict, *, fallback: list[str]) -> list[str]:
    ac = out.get("available_columns")
    if isinstance(ac, list) and ac:
        return [str(c) for c in ac]
    sga = out.get("schema_grounded_analysis")
    if isinstance(sga, dict):
        cp = sga.get("columns_present")
        if isinstance(cp, list) and cp:
            return [str(c) for c in cp]
    return list(fallback)


def _wrap_detect_bot_cluster_envelope(out: dict, *, status: str) -> dict:
    """Always attach `status` + `data` while preserving top-level keys for existing UI parsers."""
    merged = dict(out)
    merged["status"] = status
    merged["data"] = dict(out)
    if status == "error":
        err = str(merged.get("error") or merged.get("message") or "Detection failed")
        merged["message"] = f"Mapping Required: {err}"
    return merged


def _try_emit_bot_hardware_lead(case_id: str, data: dict) -> None:
    """Auto-pin dominant canvas+IP rings to the Evidence Board (Active Leads sidebar). Dedupes OPEN pins per fingerprint."""
    if not isinstance(data, dict) or data.get("ok") is not True:
        return
    hw = data.get("hardware_ip_forensics")
    if not isinstance(hw, dict) or not hw.get("pin_eligible"):
        return
    preview = str(hw.get("dominant_canvas_fingerprint") or "")[:200]
    if not preview.strip():
        return
    db = SessionLocal()
    try:
        for row in db.query(Lead).filter(Lead.case_id == case_id, Lead.status == "OPEN").all():
            rd = row.raw_data_ref or {}
            if rd.get("pin_kind") == "hardware_canvas" and rd.get("fingerprint_preview") == preview:
                return
        lid = new_lead_id()
        share = float(hw.get("share_pct_on_dominant") or 0.0)
        raw_data_ref = {
            "pin_kind": "hardware_canvas",
            "fingerprint_preview": preview,
            "fingerprint_full": str(hw.get("dominant_canvas_fingerprint_full") or "")[:512],
            "unique_ips_on_dominant": hw.get("unique_ips_on_dominant"),
            "unique_accounts_on_dominant": hw.get("unique_accounts_on_dominant"),
            "share_pct_on_dominant": share,
            "verdict_label": hw.get("verdict_label"),
            "critical_hardware_spoofing": hw.get("critical_hardware_spoofing"),
            "pinned_to_active_leads": True,
        }
        acct = int(hw.get("unique_accounts_on_dominant") or 0)
        dips = int(hw.get("unique_ips_on_dominant") or 0)
        desc = (
            f"Hardware pin: {preview} — {acct} accounts, {dips} distinct IPs "
            f"({share:.1f}% share on dominant fingerprint)."
        )
        sev = 0.98 if hw.get("critical_hardware_spoofing") else 0.88
        lead = Lead(
            id=lid,
            case_id=case_id,
            description=desc,
            severity_score=sev,
            raw_data_ref=raw_data_ref,
            status="OPEN",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        payload = LeadOut.model_validate(lead).model_dump(mode="json")
        push_lead_event(case_id, {"type": "lead_created", "lead": payload})
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


@tool
def detect_bot_clusters_tool(timestamp_column: str = "", user_id_column: str = "") -> str:
    """Run Polars bot-farm detection on the **active case CSV** (path comes from context—do not pass file paths
    or invented parameters like case_csv). Uses fuzzy + alias column bridging (acc_id→user_id, etc.); avoids hard
    'need_columns' failures by returning degraded canvas×IP forensics when time/user cannot be resolved. JSON includes
    `kind: bot_hardware_forensic` and `hardware_ip_forensics` for the Hardware vs IP Forensic Card UI. When a
    dominant fingerprint shows high IP diversity, an Evidence Board lead may be auto-created (Active Leads).

    **Envelope:** Every return is a JSON object with `status` (`success`|`error`) and `data` (the full detector
    dict, same as top-level fields) so the UI never receives a non-object; uncaught exceptions become `status: error`
    with `message` and `columns_found`."""
    path = dataset_path_ctx.get()
    if not path:
        err = "No dataset path in context. Select a case with a CSV."
        payload = {
            "ok": False,
            "error": err,
            "status": "error",
            "message": f"Mapping Required: {err}",
            "columns_found": [],
            "data": None,
        }
        return json.dumps(payload, default=str)

    cols_hint = _peek_dataset_columns(path)
    ts = (timestamp_column or "").strip() or None
    uid = (user_id_column or "").strip() or None
    try:
        raw = detect_bot_clusters(path, timestamp_column=ts, user_id_column=uid)
        out = dict(raw) if isinstance(raw, dict) else {"ok": False, "error": "Unexpected detector return type."}
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        payload = {
            "ok": False,
            "error": err,
            "status": "error",
            "message": f"Mapping Required: {err}",
            "columns_found": cols_hint,
            "data": None,
        }
        return json.dumps(payload, default=str)

    status = "success" if out.get("ok") is not False else "error"
    wrapped = _wrap_detect_bot_cluster_envelope(out, status=status)
    if status == "error":
        wrapped["columns_found"] = _columns_found_from_detector(out, fallback=cols_hint)

    cid = case_id_ctx.get()
    if cid and out.get("ok") is True:
        _try_emit_bot_hardware_lead(cid, out)

    return json.dumps(wrapped, default=str)


@tool
def find_fraud_rings_tool() -> str:
    """Graph-based fraud ring finder on the case CSV (Polars + NetworkX). Builds account linkage edges
    from shared device / address / phone, payment edges from payer→payee columns, detects directed money
    cycles (A→B→C→A), runs Louvain communities on the account projection, flags intense employee↔account
    touches, classifies nodes as hub / bridge / mule / peripheral, and returns graph_data for visualization
    plus internal_external_flags and linkage_alerts. Requires meaningful columns (see get_dataset_schema).
    For offline analysis in **Gephi**, use the API **POST /api/cases/{case_id}/network/export** with
    `"export_format": "gexf"` or `"graphml"`."""
    path = dataset_path_ctx.get()
    if not path:
        return json.dumps({"ok": False, "error": "No dataset path in context. Select a case with a CSV."})
    return json.dumps(find_fraud_rings(path), default=str)


@tool
def profile_fraud_ring_roles_tool(find_fraud_rings_json: str) -> str:
    """Given the JSON string returned by find_fraud_rings_tool, summarize kingpins (hubs), bridges, and mules
    with sample account ids for narrative reporting."""
    try:
        data = json.loads(find_fraud_rings_json or "{}")
    except json.JSONDecodeError as exc:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {exc}"})
    roles = data.get("node_roles") or {}
    if not isinstance(roles, dict):
        return json.dumps({"ok": False, "error": "node_roles missing or not an object."})
    summary = summarize_roles({str(k): v for k, v in roles.items() if isinstance(v, dict)})
    return json.dumps({"ok": True, "role_summary": summary, "raw_roles": roles}, default=str)


@tool
def analyze_ato_risk_tool(user_id: str = "", current_session_json: str = "{}", user_column: str = "") -> str:
    """Compare live session telemetry to the user's historical baseline in DuckDB.

    **Self-healing:** If ``user_id`` is blank, the server resolves ``user_id`` / ``acc_id`` (etc.) from the dataset
    schema and picks the most frequent non-null account id—no guessing in Python.

    **Behavioral profile:** ``build_user_behavioral_profile`` runs inside this tool before risk scoring; you do not
    need a separate profile call first (optional for narrative context).

    Pass ``current_session_json`` as a compact JSON object string, e.g.
    ``{"latitude":..,"longitude":..,"timestamp":"ISO-8601",...}``.
    """
    p = duckdb_path_ctx.get()
    if not p:
        return json.dumps(
            {"ok": False, "error": "No DuckDB in context; ingest a CSV for this case first."},
        )
    uid = (user_id or "").strip()
    try:
        sess = json.loads(current_session_json or "{}")
    except json.JSONDecodeError as exc:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {exc}"})
    if not isinstance(sess, dict):
        return json.dumps({"ok": False, "error": "current_session_json must decode to an object."})
    uc = (user_column or "").strip() or None
    return json.dumps(analyze_ato_risk(p, uid, sess, user_column=uc), default=str)


@tool
def search_historical_overlap_tool(entity_id: str, entity_type: str) -> str:
    """Search the Global Warehouse: find other cases where this user_id, ip_address, device_id, or card_hash appeared.
    entity_type must be one of: user_id, ip_address, device_id, card_hash (aliases: ip, user, device, card).
    Uses the active case id from context to exclude the current investigation from recidivist counts."""
    cid = case_id_ctx.get()
    return json.dumps(
        run_search_historical_overlap(
            (entity_id or "").strip(),
            (entity_type or "").strip(),
            exclude_case_id=cid,
        ),
        default=str,
    )


@tool
def warehouse_query_tool(sql: str) -> str:
    """Run a single read-only SELECT (or WITH ... SELECT) on the Global Warehouse DuckDB.
    Tables: warehouse_events (source_case_id, upload_timestamp, source_filename, row_index, row_json),
    entity_occurrences (source_case_id, upload_timestamp, entity_type, entity_value, source_column),
    entity_map (entity_type, entity_value, distinct_case_count, first_seen, last_seen, case_ids).
    Use for SQL joins and filters across source_case_id — never ask the operator for historical CSVs."""
    return json.dumps(run_warehouse_query(sql or ""), default=str)


@tool
def warehouse_search_text_tool(needle: str, limit: int = 40) -> str:
    """Search ingested warehouse_events for a substring in row_json or source_filename (dataset names, stress tests, tags).
    Call when the operator names a specific test or table before answering from memory."""
    return json.dumps(run_warehouse_text_search(needle, limit=int(limit or 40)), default=str)


@tool
def humanoid_stress_test_linkage_tool() -> str:
    """Humanoid stress test: query GlobalWarehouse for indexed Humanoid rows (stress IP 1.1.1.1) and align with the
    active case CSV for canvas_fingerprint / device_id overlap. When hits exist, you MUST state in your narrative the
    exact sentence in field `required_narrative` from the tool JSON (Bot Cluster / dataset linkage)."""
    return json.dumps(
        run_humanoid_stress_test_linkage(
            exclude_case_id=case_id_ctx.get(),
            dataset_path=dataset_path_ctx.get(),
        ),
        default=str,
    )


_TOOL_BY_NAME: dict[str, object] = {
    "get_dataset_schema": get_dataset_schema,
    "execute_in_sandbox": execute_in_sandbox,
    "emit_lead": emit_lead,
    "analyze_chargeback_risk_tool": analyze_chargeback_risk_tool,
    "chargeback_trust_velocity_tool": chargeback_trust_velocity_tool,
    "build_representment_manifest_tool": build_representment_manifest_tool,
    "simulate_representment_tool": simulate_representment_tool,
    "build_user_behavioral_profile_tool": build_user_behavioral_profile_tool,
    "analyze_ato_risk_tool": analyze_ato_risk_tool,
    "detect_bot_clusters_tool": detect_bot_clusters_tool,
    "batch_flag_bot_cluster_tool": batch_flag_bot_cluster_tool,
    "find_fraud_rings_tool": find_fraud_rings_tool,
    "profile_fraud_ring_roles_tool": profile_fraud_ring_roles_tool,
    "search_historical_overlap_tool": search_historical_overlap_tool,
    "warehouse_query_tool": warehouse_query_tool,
    "warehouse_search_text_tool": warehouse_search_text_tool,
    "humanoid_stress_test_linkage_tool": humanoid_stress_test_linkage_tool,
}

# Stable bind order: schema + filing first, then specialist tools.
_ANALYST_TOOL_ORDER: tuple[str, ...] = (
    "get_dataset_schema",
    "execute_in_sandbox",
    "emit_lead",
    "chargeback_trust_velocity_tool",
    "analyze_chargeback_risk_tool",
    "build_representment_manifest_tool",
    "simulate_representment_tool",
    "build_user_behavioral_profile_tool",
    "analyze_ato_risk_tool",
    "detect_bot_clusters_tool",
    "batch_flag_bot_cluster_tool",
    "find_fraud_rings_tool",
    "profile_fraud_ring_roles_tool",
    "warehouse_query_tool",
    "warehouse_search_text_tool",
    "humanoid_stress_test_linkage_tool",
)

_GENERAL_WAREHOUSE_FIRST: tuple[str, ...] = (
    "warehouse_search_text_tool",
    "warehouse_query_tool",
    "humanoid_stress_test_linkage_tool",
)


def build_analyst_tools(persona_id: str | None = None) -> list:
    """Analyst path: tools gated by FraudAgent.allowlist plus mandatory cross-case warehouse search."""
    agent = get_fraud_agent(persona_id)
    allowed = agent.allowed_tool_names
    out: list = []
    wh = _TOOL_BY_NAME.get("search_historical_overlap_tool")
    if wh is not None and agent.agent_type == "general":
        out.append(wh)
    if agent.agent_type == "general":
        for name in _GENERAL_WAREHOUSE_FIRST:
            if name not in allowed:
                continue
            t = _TOOL_BY_NAME.get(name)
            if t is not None:
                out.append(t)
    for name in _ANALYST_TOOL_ORDER:
        if agent.agent_type == "general" and name in _GENERAL_WAREHOUSE_FIRST:
            continue
        if name not in allowed:
            continue
        t = _TOOL_BY_NAME.get(name)
        if t is not None:
            out.append(t)
    if wh is not None and agent.agent_type != "general":
        out.append(wh)
    return out
