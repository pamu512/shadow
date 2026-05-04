"""ML threshold optimization API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback_async
from backend.database.models import Case
from backend.schemas import OptimizeThresholdsRequest, OptimizeThresholdsResponse
from backend.tools.optimize_thresholds import run_optimize

router = APIRouter(prefix="/api", tags=["thresholds"])


@router.post("/optimize-thresholds", response_model=OptimizeThresholdsResponse)
async def optimize_thresholds(
    body: OptimizeThresholdsRequest, db: AsyncSession = Depends(get_db)
) -> OptimizeThresholdsResponse:
    path = body.dataset_path
    if not path and body.case_id:
        r = await db.execute(select(Case).where(Case.id == body.case_id))
        c = r.scalar_one_or_none()
        path = c.dataset_path if c else None
    path = await resolve_with_active_fallback_async(db, path)
    if not path:
        raise HTTPException(400, "No dataset path provided (case CSV missing and no active case CSV).")
    result = await run_in_threadpool(
        run_optimize, path, body.model, body.target_column, body.optimization_objective
    )
    if body.case_id:
        r = await db.execute(select(Case).where(Case.id == body.case_id))
        c = r.scalar_one_or_none()
        if c:
            c.last_optimization_manifest = result["optimization_manifest"]
            await db.commit()
    return OptimizeThresholdsResponse(
        thresholds=result["thresholds"],
        optimization_manifest=result["optimization_manifest"],
        metrics_at_threshold=result["metrics_at_threshold"],
        optimization_objective=result["optimization_objective"],
    )
