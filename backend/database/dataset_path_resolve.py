"""Resolve CSV paths for tools/APIs: fall back to the globally active case when primary is unset."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.database.models import Case


def active_case_dataset_path(db: Session) -> str | None:
    row = db.query(Case).filter(Case.is_active.is_(True)).first()
    if row and row.dataset_path:
        s = str(row.dataset_path).strip()
        return s or None
    return None


def resolve_with_active_fallback(db: Session, primary: str | None) -> str | None:
    if primary and str(primary).strip():
        return str(primary).strip()
    return active_case_dataset_path(db)
