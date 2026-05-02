"""Scaffold generation endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.models import Case
from backend.schemas import ScaffoldRequest, ScaffoldResponse
from backend.tools.dataset_schema import describe_csv
from backend.tools.scaffold_code import generate_scaffold

router = APIRouter(prefix="/api", tags=["scaffold"])


@router.post("/scaffold", response_model=ScaffoldResponse)
def scaffold(body: ScaffoldRequest, db: Session = Depends(get_db)) -> ScaffoldResponse:
    cols = body.columns
    if cols is None and body.case_id:
        c = db.query(Case).filter(Case.id == body.case_id).first()
        if c and c.dataset_path:
            info = describe_csv(c.dataset_path)
            cols = info.get("columns") if "columns" in info else None
    code, explanation = generate_scaffold(body.language, body.intent, cols)
    return ScaffoldResponse(code=code, explanation=explanation)
