"""Script code review."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.agent.ollama import get_llm
from backend.database import get_db
from backend.database.models import Case
from backend.schemas import CodeReviewRequest, CodeReviewResponse
from backend.tools.code_review_lib import review_script

router = APIRouter(prefix="/api", tags=["code_review"])


@router.post("/code-review", response_model=CodeReviewResponse)
def code_review(body: CodeReviewRequest, db: Session = Depends(get_db)) -> CodeReviewResponse:
    ds = None
    if body.case_id:
        c = db.query(Case).filter(Case.id == body.case_id).first()
        if c:
            ds = c.dataset_path
    else:
        a = db.query(Case).filter(Case.is_active.is_(True)).first()
        ds = a.dataset_path if a else None
    orig, sug, notes = review_script(body.script, body.language, ds, llm=get_llm())
    return CodeReviewResponse(original=orig, suggested=sug, notes=notes)
