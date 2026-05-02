"""Global cross-case warehouse (DuckDB) read APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas import WarehouseOverlapOut
from backend.tools.global_search import search_historical_overlap

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"])


@router.get("/overlap", response_model=WarehouseOverlapOut)
def get_overlap(
    entity_id: str = Query(..., min_length=1, max_length=512),
    entity_type: str = Query(..., min_length=2, max_length=64),
    exclude_case_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
) -> WarehouseOverlapOut:
    """Resolve cross-case overlap for workspace / manual checks (same logic as the agent tool)."""
    _ = db  # reserved for future case ACL checks
    raw = search_historical_overlap(
        entity_id,
        entity_type,
        exclude_case_id=exclude_case_id,
    )
    if raw.get("ok") is False:
        raise HTTPException(400, str(raw.get("error") or "overlap query failed"))
    return WarehouseOverlapOut.model_validate(raw)
