"""Polyglot sandbox execution."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback_async
from backend.database.models import Case
from backend.schemas import ExecuteRequest, ExecuteResponse
from backend.tools.audit_log import record_audit_async
from backend.tools.sandbox_exec import execute_code

router = APIRouter(prefix="/api", tags=["execute"])


@router.post("/execute", response_model=ExecuteResponse)
async def run_code(body: ExecuteRequest, db: AsyncSession = Depends(get_db)) -> ExecuteResponse:
    ds_path = None
    if body.case_id:
        r = await db.execute(select(Case).where(Case.id == body.case_id))
        c = r.scalar_one_or_none()
        if c:
            ds_path = c.dataset_path
    else:
        ar = await db.execute(select(Case).where(Case.is_active.is_(True)).limit(1))
        a = ar.scalar_one_or_none()
        ds_path = a.dataset_path if a else None
    ds_path = await resolve_with_active_fallback_async(db, ds_path)
    if ds_path:
        os.environ["FRAUD_DATASET_PATH"] = str(Path(ds_path).resolve())
    out = execute_code(body.language, body.code, timeout_sec=body.timeout_sec)
    if body.case_id:
        notes = (out["stdout"] or out["stderr"] or "").strip() or None
        await record_audit_async(
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
