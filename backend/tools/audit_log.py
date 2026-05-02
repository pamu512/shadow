"""Append-only audit trail rows for case activity."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.database.models import AuditLog


def record_audit(
    db: Session,
    *,
    case_id: str,
    action_taken: str,
    code_executed: str | None = None,
    agent_notes: str | None = None,
    max_code: int = 24_000,
    max_notes: int = 8_000,
) -> None:
    code = (code_executed or None) and (code_executed[:max_code] if len(code_executed) > max_code else code_executed)
    notes = (agent_notes or None) and (agent_notes[:max_notes] if len(agent_notes) > max_notes else agent_notes)
    db.add(
        AuditLog(
            case_id=case_id,
            action_taken=action_taken,
            code_executed=code,
            agent_notes=notes,
        )
    )
    db.commit()
