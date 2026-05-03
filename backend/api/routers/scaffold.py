"""Scaffold generation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback
from backend.database.models import Case
from backend.schemas import ScaffoldRequest, ScaffoldResponse
from backend.tools.dataset_schema import describe_csv
from backend.tools.scaffold_code import generate_scaffold

router = APIRouter(prefix="/api", tags=["scaffold"])


@router.post("/scaffold", response_model=ScaffoldResponse)
def scaffold(body: ScaffoldRequest, db: Session = Depends(get_db)) -> ScaffoldResponse:
    cols = body.columns
    path_for_schema: str | None = None
    if body.case_id:
        c = db.query(Case).filter(Case.id == body.case_id).first()
        path_for_schema = resolve_with_active_fallback(db, c.dataset_path if c else None)
    else:
        path_for_schema = resolve_with_active_fallback(db, None)
    if cols is None and path_for_schema:
        info = describe_csv(path_for_schema)
        cols = info.get("columns") if "columns" in info else None
    code, explanation = generate_scaffold(body.language, body.intent, cols)
    return ScaffoldResponse(code=code, explanation=explanation)
