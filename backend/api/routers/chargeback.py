"""Chargeback analysis, representment manifest, and package download."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback
from backend.database.models import Case
from backend.schemas import SimulateRepresentmentRequest
from backend.tools.chargeback_analyzer import analyze_chargeback_risk
from backend.tools.evidence_builder import build_representment_manifest, representment_package_bytes
from backend.tools.representment_simulation import simulate_issuer_representment_review

router = APIRouter(prefix="/api/cases", tags=["chargeback"])


def _get_case(case_id: str, db: Session) -> Case:
    row = db.query(Case).filter(Case.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row


@router.post("/{case_id}/chargeback/simulate-representment")
def chargeback_simulate_representment(
    case_id: str,
    body: SimulateRepresentmentRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """LLM role-play: issuing bank analyst judges whether merchant evidence is likely strong enough."""
    case = _get_case(case_id, db)
    path = resolve_with_active_fallback(db, case.dataset_path)
    if not path:
        raise HTTPException(status_code=400, detail="Case has no dataset.")
    tid = (body.transaction_id.strip() if body and body.transaction_id else None) or None
    return simulate_issuer_representment_review(path, transaction_id=tid)


@router.post("/{case_id}/chargeback/analyze")
def chargeback_analyze(case_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run friendly-fraud / chargeback evidence scan on the case CSV."""
    case = _get_case(case_id, db)
    path = resolve_with_active_fallback(db, case.dataset_path)
    if not path:
        raise HTTPException(status_code=400, detail="Case has no dataset; upload a CSV first.")
    return analyze_chargeback_risk(path)


@router.get("/{case_id}/chargeback/manifest")
def chargeback_manifest(
    case_id: str,
    transaction_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """JSON Representment Manifest for one transaction."""
    case = _get_case(case_id, db)
    path = resolve_with_active_fallback(db, case.dataset_path)
    if not path:
        raise HTTPException(status_code=400, detail="Case has no dataset.")
    return build_representment_manifest(transaction_id.strip(), path)


@router.get("/{case_id}/chargeback/package.zip")
def chargeback_package_zip(
    case_id: str,
    transaction_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> Response:
    """Zip export: representment_manifest.json + REPRESENTMENT_SUMMARY.txt."""
    case = _get_case(case_id, db)
    path = resolve_with_active_fallback(db, case.dataset_path)
    if not path:
        raise HTTPException(status_code=400, detail="Case has no dataset.")
    manifest = build_representment_manifest(transaction_id.strip(), path)
    if not manifest.get("ok"):
        raise HTTPException(status_code=400, detail=manifest.get("error", "Manifest build failed"))
    analysis = analyze_chargeback_risk(path)
    summary = ""
    if isinstance(analysis, dict) and analysis.get("ok"):
        summary = "\n".join(analysis.get("executive_summary") or [])[:8000]
    blob = representment_package_bytes(manifest, summary_text=summary or None)
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", transaction_id.strip())[:80] or "tx"
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="representment_{safe}.zip"'},
    )
