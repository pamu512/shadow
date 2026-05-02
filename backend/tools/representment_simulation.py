"""Issuer-bank-style representment adjudication via LLM (simulation, not legal advice)."""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.ollama import get_llm
from backend.tools.chargeback_analyzer import analyze_chargeback_risk
from backend.tools.evidence_builder import build_representment_manifest

_ISSUER_SYSTEM = """You are a senior chargeback analyst at a major card issuer (Visa/Mastercard rules \
environment). A merchant has submitted representment evidence; you are reviewing a structured internal \
summary produced by their fraud-ops tooling (JSON below). This is a desk simulation only.

Instructions:
- Respond in first person as the issuing bank (e.g. "We would…", "Our chargeback team would likely require…").
- Say clearly whether the package is **likely sufficient** to overturn the chargeback in the merchant's favor, \
or **unlikely / borderline**, given only what appears in the JSON. Use calibrated language — not a guarantee.
- Cite **concrete facts** that appear in the payload (transaction id, dates, IPs, device ids, tracking hints, \
login times, AVS/CVV strings, etc.). If a fact is missing, call that out as an evidence gap.
- List **strengths** and **weaknesses** as short bullets.
- Be professionally skeptical: issuer analysts discount vague narratives and missing proof of delivery/service.
- Do not invent tracking numbers, timestamps, or dollar amounts not present in the JSON.
- Target 350–550 words unless the payload is nearly empty — then state the minimum documents you would need \
(POD, IP/device logs, usage logs, ToS acceptance, etc.).
- End with one sentence: simulated **_issuer leaning_**: MERCHANT_FAVORABLE, ISSUER_FAVORABLE (cardholder), or SPLIT."""


def _slim_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    if not analysis.get("ok"):
        return analysis
    indicators = analysis.get("friendly_fraud_indicators") or {}
    slim_ind: dict[str, Any] = {}
    for k, v in indicators.items():
        if isinstance(v, list):
            slim_ind[k] = v[:8]
        else:
            slim_ind[k] = v
    return {
        "ok": True,
        "chargeback_risk_score": analysis.get("chargeback_risk_score"),
        "win_probability_percent": analysis.get("win_probability_percent"),
        "executive_summary": analysis.get("executive_summary"),
        "columns_resolved": analysis.get("columns_resolved"),
        "disputed_row_count": analysis.get("disputed_row_count"),
        "friendly_fraud_indicators_sample": slim_ind,
    }


def _slim_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not manifest.get("ok"):
        return manifest
    row = manifest.get("source_row")
    if isinstance(row, dict) and len(row) > 40:
        row = {k: row[k] for k in list(row.keys())[:40]}
    return {
        "ok": True,
        "transaction_id": manifest.get("transaction_id"),
        "proof_of_service": manifest.get("proof_of_service"),
        "proof_of_delivery": manifest.get("proof_of_delivery"),
        "policy_acknowledgment": manifest.get("policy_acknowledgment"),
        "authentication": manifest.get("authentication"),
        "communication_history": manifest.get("communication_history"),
        "source_row_preview": row,
    }


def simulate_issuer_representment_review(
    dataset_path: str,
    *,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    """
    Run automated scan + optional manifest, then ask the local LLM to role-play an issuer adjudicator.

    Returns JSON including issuer_perspective_memo (plain text) and ok/error.
    """
    analysis = analyze_chargeback_risk(dataset_path)
    manifest: dict[str, Any] | None = None
    tid = (transaction_id or "").strip() or None
    if tid:
        manifest = build_representment_manifest(tid, dataset_path)

    payload = {
        "simulation": "issuer_representment_review",
        "transaction_id_filter": tid,
        "automated_evidence_scan": _slim_analysis(analysis),
        "representment_manifest": _slim_manifest(manifest) if manifest else None,
    }

    body = json.dumps(payload, indent=2, default=str)
    if len(body) > 100_000:
        body = body[:99_500] + "\n…[truncated for model context]"

    try:
        llm = get_llm()
        msg = llm.invoke(
            [
                SystemMessage(content=_ISSUER_SYSTEM),
                HumanMessage(
                    content=(
                        "Merchant evidence package (JSON). Render your issuer adjudication memo.\n\n"
                        f"```json\n{body}\n```"
                    )
                ),
            ]
        )
        text = msg.content if hasattr(msg, "content") else str(msg)
        return {
            "ok": True,
            "issuer_perspective_memo": text,
            "transaction_id": tid,
            "model_note": "Simulated issuer view; not legal or scheme advice. Tune with your issuer partner.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Issuer simulation failed (LLM): {exc}",
            "transaction_id": tid,
        }
