"""Polyglot sandbox execution."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.database.models import Case
from backend.schemas import ExecuteRequest, ExecuteResponse
from backend.tools.audit_log import record_audit
from backend.tools.sandbox_exec import execute_code

router = APIRouter(prefix="/api", tags=["execute"])


@router.post("/execute", response_model=ExecuteResponse)
def run_code(body: ExecuteRequest, db: Session = Depends(get_db)) -> ExecuteResponse:
    ds_path = None
    if body.case_id:
        c = db.query(Case).filter(Case.id == body.case_id).first()
        if c:
            ds_path = c.dataset_path
    else:
        a = db.query(Case).filter(Case.is_active.is_(True)).first()
        ds_path = a.dataset_path if a else None
    if ds_path:
        os.environ["FRAUD_DATASET_PATH"] = str(Path(ds_path).resolve())
    out = execute_code(body.language, body.code, timeout_sec=body.timeout_sec)
    if body.case_id:
        notes = (out["stdout"] or out["stderr"] or "").strip() or None
        record_audit(
            db,
            case_id=body.case_id,
            action_taken=f"Sandbox execution ({body.language})",
            code_executed=body.code,
            agent_notes=notes,
        )
    return ExecuteResponse(
        stdout=out["stdout"],
        stderr=out["stderr"],
        exit_code=out["exit_code"],
        plots_base64=out["plots_base64"],
        violations=out.get("violations"),
    )
