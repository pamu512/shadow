"""Bot cluster detection and bulk flagging (CSV / Polars)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.database.models import Case
from backend.schemas import BotBulkSuspendRequest
from backend.agent.tools_langchain import _try_emit_bot_hardware_lead
from backend.tools.bot_detector import detect_bot_clusters
from backend.tools.bulk_manager import batch_flag_accounts

router = APIRouter(prefix="/api/cases", tags=["bots"])

# backend/api/routers/bots.py -> parents[3] == repository root (shadow/)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_case_csv_for_detection(case: Case) -> Path:
    """
    Resolve the on-disk CSV for bot detection.

    Upload flow stores an absolute path, but older rows or different host cwd can leave paths that
    only resolve from repo root, workspace, or the per-case datasets folder.
    """
    raw = (case.dataset_path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Case has no dataset_path; upload a CSV first.")
    p = Path(raw).expanduser()
    if p.is_file():
        return p.resolve()

    rel = Path(raw)
    name = rel.name if rel.name else raw.split("/")[-1].split("\\")[-1]

    candidates: list[Path] = []
    if not rel.is_absolute():
        candidates.append((_REPO_ROOT / rel).resolve())
        candidates.append((settings.workspace_dir / rel).resolve())
    candidates.append((settings.datasets_storage_dir / case.id / name).resolve())
    if rel.is_absolute():
        candidates.append(rel.resolve())

    for cand in candidates:
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue

    return p


def _get_case(case_id: str, db: Session) -> Case:
    row = db.query(Case).filter(Case.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row


@router.post("/{case_id}/bots/detect")
def bot_detect_clusters(case_id: str, db: Session = Depends(get_db)) -> dict:
    case = _get_case(case_id, db)
    csv_path = _resolve_case_csv_for_detection(case)
    out = detect_bot_clusters(csv_path)
    _try_emit_bot_hardware_lead(case_id, out)
    return out


@router.post("/{case_id}/bots/bulk-suspend")
def bot_bulk_suspend(case_id: str, body: BotBulkSuspendRequest, db: Session = Depends(get_db)) -> dict:
    _get_case(case_id, db)
    return batch_flag_accounts(
        db,
        case_id=case_id,
        account_ids=body.account_ids,
        reason=body.reason,
        cluster_id=body.cluster_id,
        action_code="BULK_BOT_SUSPEND",
    )
