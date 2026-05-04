"""Script code review."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.ollama import get_llm
from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback_async
from backend.database.models import Case
from backend.schemas import CodeReviewRequest, CodeReviewResponse
from starlette.concurrency import run_in_threadpool

from backend.tools.code_review_lib import review_script

router = APIRouter(prefix="/api", tags=["code_review"])


@router.post("/code-review", response_model=CodeReviewResponse)
async def code_review(body: CodeReviewRequest, db: AsyncSession = Depends(get_db)) -> CodeReviewResponse:
    ds = None
    if body.case_id:
        r = await db.execute(select(Case).where(Case.id == body.case_id))
        c = r.scalar_one_or_none()
        if c:
            ds = c.dataset_path
    else:
        ar = await db.execute(select(Case).where(Case.is_active.is_(True)).limit(1))
        a = ar.scalar_one_or_none()
        ds = a.dataset_path if a else None
    ds = await resolve_with_active_fallback_async(db, ds)
    llm = get_llm()
    orig, sug, notes = await run_in_threadpool(review_script, body.script, body.language, ds, llm=llm)
    return CodeReviewResponse(original=orig, suggested=sug, notes=notes)
