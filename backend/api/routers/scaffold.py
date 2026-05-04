"""Scaffold generation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback_async
from backend.database.models import Case
from backend.schemas import ScaffoldRequest, ScaffoldResponse
from backend.tools.dataset_schema import describe_csv
from backend.tools.scaffold_code import generate_scaffold

router = APIRouter(prefix="/api", tags=["scaffold"])


def _scaffold_sync(
    language: str,
    intent: str,
    columns: list[dict[str, str]] | None,
    path_for_schema: str | None,
) -> ScaffoldResponse:
    cols = columns
    if cols is None and path_for_schema:
        info = describe_csv(path_for_schema)
        cols = info.get("columns") if "columns" in info else None
    code, explanation = generate_scaffold(language, intent, cols)
    return ScaffoldResponse(code=code, explanation=explanation)


@router.post("/scaffold", response_model=ScaffoldResponse)
async def scaffold(body: ScaffoldRequest, db: AsyncSession = Depends(get_db)) -> ScaffoldResponse:
    path_for_schema: str | None = None
    if body.case_id:
        r = await db.execute(select(Case).where(Case.id == body.case_id))
        c = r.scalar_one_or_none()
        path_for_schema = await resolve_with_active_fallback_async(db, c.dataset_path if c else None)
    else:
        path_for_schema = await resolve_with_active_fallback_async(db, None)
    return await run_in_threadpool(
        _scaffold_sync,
        body.language,
        body.intent,
        body.columns,
        path_for_schema,
    )
