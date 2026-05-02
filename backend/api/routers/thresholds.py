"""ML threshold optimization API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.models import Case
from backend.schemas import OptimizeThresholdsRequest, OptimizeThresholdsResponse
from backend.tools.optimize_thresholds import run_optimize

router = APIRouter(prefix="/api", tags=["thresholds"])


@router.post("/optimize-thresholds", response_model=OptimizeThresholdsResponse)
def optimize_thresholds(body: OptimizeThresholdsRequest, db: Session = Depends(get_db)) -> OptimizeThresholdsResponse:
    path = body.dataset_path
    if not path and body.case_id:
        c = db.query(Case).filter(Case.id == body.case_id).first()
        if not c or not c.dataset_path:
            raise HTTPException(400, "Case has no dataset_path")
        path = c.dataset_path
    if not path:
        active = db.query(Case).filter(Case.is_active.is_(True)).first()
        if not active or not active.dataset_path:
            raise HTTPException(400, "No dataset path provided")
        path = active.dataset_path
    result = run_optimize(path, body.model, body.target_column, body.optimization_objective)
    if body.case_id:
        c = db.query(Case).filter(Case.id == body.case_id).first()
        if c:
            c.last_optimization_manifest = result["optimization_manifest"]
            db.commit()
    return OptimizeThresholdsResponse(
        thresholds=result["thresholds"],
        optimization_manifest=result["optimization_manifest"],
        metrics_at_threshold=result["metrics_at_threshold"],
        optimization_objective=result["optimization_objective"],
    )
