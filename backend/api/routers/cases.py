"""Cases CRUD, CSV upload + DuckDB ingest, preview, activity."""
from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import polars as pl
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.agent.coordinator import build_persona_suggestion
from backend.case_status import normalize_case_status
from backend.config import settings
from backend.data.warehouse import GlobalWarehouse
from backend.database import IngestionEngine, get_db
from backend.database.models import AuditLog, Case, Lead
from backend.schemas import (
    ActivityBulkRequest,
    ActivityBulkResponse,
    ActivitySeriesPayload,
    CaseCreate,
    CaseOut,
    CasePatch,
    CasesPurgeOut,
    EvidenceBoardResponse,
    LeadOut,
    LeadStatusPatch,
    AuditLogOut,
)
from backend.tools.case_activity import compute_case_activity

router = APIRouter(prefix="/api/cases", tags=["cases"])
_log = logging.getLogger(__name__)

_STATUS_SORT = case(
    (Case.status == "FLAGGED", 0),
    (Case.status == "INVESTIGATING", 1),
    (Case.status == "CLEARED", 2),
    else_=3,
)


def _memory_aggregates(
    db: Session, ids: list[str]
) -> tuple[dict[str, int], dict[str, tuple[int, datetime | None, int]]]:
    if not ids:
        return {}, {}
    lead_counts = dict(
        db.query(Lead.case_id, func.count(Lead.id))
        .filter(Lead.case_id.in_(ids))
        .group_by(Lead.case_id)
        .all()
    )
    aud_rows = (
        db.query(
            AuditLog.case_id,
            func.count(AuditLog.id).label("ev"),
            func.max(AuditLog.timestamp).label("last_ts"),
            func.sum(case((AuditLog.code_executed.isnot(None), 1), else_=0)).label("scripts"),
        )
        .filter(AuditLog.case_id.in_(ids))
        .group_by(AuditLog.case_id)
        .all()
    )
    aud: dict[str, tuple[int, datetime | None, int]] = {}
    for r in aud_rows:
        scripts_val = getattr(r, "scripts", None)
        ts = r.last_ts
        aud[r.case_id] = (
            int(r.ev or 0),
            ts if isinstance(ts, datetime) else None,
            int(scripts_val or 0),
        )
    return lead_counts, aud


def _case_to_out(db: Session, row: Case) -> CaseOut:
    lc, aud = _memory_aggregates(db, [row.id])
    n_lead = lc.get(row.id, 0)
    ev, last_ts, n_script = aud.get(row.id, (0, None, 0))
    return CaseOut(
        id=row.id,
        name=row.name,
        dataset_path=row.dataset_path,
        duckdb_path=row.duckdb_path,
        is_active=row.is_active,
        status=normalize_case_status(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        schema_summary=row.schema_summary,
        lead_count=n_lead,
        evidence_event_count=ev,
        script_run_count=n_script,
        last_memory_at=last_ts,
        persona_suggestion=build_persona_suggestion(row.schema_summary if isinstance(row.schema_summary, dict) else None),
    )


@router.get("", response_model=list[CaseOut])
def list_cases(db: Session = Depends(get_db)) -> list[CaseOut]:
    cases = db.query(Case).order_by(_STATUS_SORT.asc(), Case.created_at.desc()).all()
    if not cases:
        return []
    return [_case_to_out(db, c) for c in cases]


@router.post("/upload", response_model=CaseOut)
def upload_case(
    name: str = Form(...),
    status: str = Form(default="INVESTIGATING"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> CaseOut:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "A .csv file is required")
    label = (name or "").strip() or "Untitled case"
    st = normalize_case_status(status)
    case_id = str(uuid.uuid4())
    engine = IngestionEngine()

    suffix = Path(file.filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        dest_csv, duck_path, summary = engine.ingest_csv(case_id, tmp_path, file.filename)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Ingestion failed: {e}") from e
    tmp_path.unlink(missing_ok=True)

    try:
        GlobalWarehouse().append_case_csv(case_id, dest_csv, file.filename)
    except Exception as wh_exc:  # noqa: BLE001
        # Case DuckDB is authoritative; warehouse is additive — log-only failure for MVP.
        _log.warning("Global warehouse append failed for %s: %s", case_id, wh_exc)

    case = Case(
        id=case_id,
        name=label,
        dataset_path=str(dest_csv.resolve()),
        is_active=False,
        status=st,
        duckdb_path=str(duck_path.resolve()),
        schema_summary=summary,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return _case_to_out(db, case)


@router.post("", response_model=CaseOut)
def create_case(body: CaseCreate, db: Session = Depends(get_db)) -> CaseOut:
    st = normalize_case_status(body.status)
    case = Case(
        id=str(uuid.uuid4()),
        name=body.name,
        dataset_path=body.dataset_path,
        is_active=False,
        status=st,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return _case_to_out(db, case)


def _remove_case_disk_warehouse(case: Case) -> None:
    try:
        GlobalWarehouse().remove_case(case.id)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Global warehouse remove failed for %s: %s", case.id, exc)
    case_dir = settings.datasets_storage_dir / case.id
    if case_dir.is_dir():
        shutil.rmtree(case_dir, ignore_errors=True)
    if case.duckdb_path:
        try:
            Path(case.duckdb_path).unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("DuckDB unlink %s: %s", case.duckdb_path, exc)


def _purge_all_cases_impl(db: Session) -> CasesPurgeOut:
    """Delete all cases, per-case ingested CSV/DuckDB files, and global-warehouse rows (local reset)."""
    rows = list(db.query(Case).order_by(Case.created_at.asc()).all())
    n = 0
    for c in rows:
        _remove_case_disk_warehouse(c)
        db.delete(c)
        n += 1
    db.commit()
    return CasesPurgeOut(ok=True, cases_removed=n)


@router.post("/purge-all", response_model=CasesPurgeOut)
def purge_all_cases_post(db: Session = Depends(get_db)) -> CasesPurgeOut:
    return _purge_all_cases_impl(db)


@router.delete("/purge-all", response_model=CasesPurgeOut)
def purge_all_cases_delete(db: Session = Depends(get_db)) -> CasesPurgeOut:
    """Same as POST /purge-all — supports clients that cannot send POST JSON reliably."""
    return _purge_all_cases_impl(db)


@router.delete("/{case_id}")
def delete_case(case_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    was_active = case.is_active
    _remove_case_disk_warehouse(case)
    db.delete(case)
    db.commit()
    if was_active:
        remaining = db.query(Case).order_by(Case.created_at.desc()).first()
        if remaining:
            for x in db.query(Case).all():
                x.is_active = x.id == remaining.id
            db.commit()
    return {"ok": True}


@router.post("/activity-bulk", response_model=ActivityBulkResponse)
def activity_bulk(body: ActivityBulkRequest, db: Session = Depends(get_db)) -> ActivityBulkResponse:
    raw_ids = list(dict.fromkeys(body.case_ids))[:64]
    out: dict[str, ActivitySeriesPayload] = {}
    for cid in raw_ids:
        case = db.query(Case).filter(Case.id == cid).first()
        path = case.dataset_path if case else None
        payload = compute_case_activity(cid, path)
        out[cid] = ActivitySeriesPayload(**payload)
    return ActivityBulkResponse(activities=out)


@router.patch("/{case_id}", response_model=CaseOut)
def patch_case(case_id: str, body: CasePatch, db: Session = Depends(get_db)) -> CaseOut:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    if body.name is not None:
        case.name = body.name
    if body.status is not None:
        case.status = normalize_case_status(body.status)
    db.commit()
    db.refresh(case)
    return _case_to_out(db, case)


@router.post("/{case_id}/activate", response_model=CaseOut)
def activate_case(case_id: str, db: Session = Depends(get_db)) -> CaseOut:
    for c in db.query(Case).all():
        c.is_active = c.id == case_id
    db.commit()
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return _case_to_out(db, case)


@router.get("/{case_id}/evidence", response_model=EvidenceBoardResponse)
def get_evidence(case_id: str, db: Session = Depends(get_db)) -> EvidenceBoardResponse:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    leads = db.query(Lead).filter(Lead.case_id == case_id).order_by(Lead.created_at.desc()).all()
    audits = (
        db.query(AuditLog)
        .filter(AuditLog.case_id == case_id)
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    return EvidenceBoardResponse(
        leads=[LeadOut.model_validate(x) for x in leads],
        audit_logs=[AuditLogOut.model_validate(x) for x in audits],
    )


@router.patch("/{case_id}/leads/{lead_id}", response_model=LeadOut)
def patch_lead(case_id: str, lead_id: str, body: LeadStatusPatch, db: Session = Depends(get_db)) -> Lead:
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.case_id == case_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.status = body.status
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/{case_id}/preview")
def preview(case_id: str, rows: int = 50, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case or not case.dataset_path:
        raise HTTPException(400, "Case or dataset path missing")
    df = pl.read_csv(case.dataset_path, try_parse_dates=True, n_rows=rows)
    return {"columns": df.columns, "rows": df.to_dicts()}
