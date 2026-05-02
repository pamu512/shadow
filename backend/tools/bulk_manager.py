"""Batch remediation hooks for bot / Sybil clusters (audit + evidence)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from backend.tools.audit_log import record_audit


def batch_flag_accounts(
    db: Session,
    *,
    case_id: str,
    account_ids: list[str],
    reason: str,
    cluster_id: str | None = None,
    action_code: str = "BULK_BOT_FLAG",
    agent_notes: str | None = None,
) -> dict[str, Any]:
    """
    Record operator intent to flag/suspend many accounts at once.
    Wire to IAM / risk engine in production; this persists an audit row.
    """
    ids = sorted({str(a).strip() for a in account_ids if str(a).strip()})
    if not ids:
        return {"ok": False, "error": "account_ids is empty after normalization."}

    payload = {
        "cluster_id": cluster_id,
        "reason": (reason or "").strip() or "BOT_CLUSTER",
        "flagged_count": len(ids),
        "account_ids": ids[:5000],
        "account_ids_truncated": max(0, len(ids) - 5000),
    }
    record_audit(
        db,
        case_id=case_id,
        action_taken=action_code,
        code_executed=json.dumps(payload, default=str)[:8000],
        agent_notes=(agent_notes or "Bulk bot-cluster remediation from Shadow.")[:8000],
    )
    return {
        "ok": True,
        "flagged_count": len(ids),
        "cluster_id": cluster_id,
        "message": "Batch flag recorded in audit trail. Connect your user store to enforce suspension.",
    }
