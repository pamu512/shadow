"""Fraud ring / collusion network analysis (graph)."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.models import Case
from backend.tools.network_analyzer import export_fraud_ring_network, find_fraud_rings

router = APIRouter(prefix="/api/cases", tags=["network"])


class NetworkRingsRequest(BaseModel):
    account_column: str | None = Field(default=None)
    payer_column: str | None = Field(default=None)
    payee_column: str | None = Field(default=None)
    amount_column: str | None = Field(default=None)


class NetworkExportRequest(NetworkRingsRequest):
    """Same column overrides as /network/rings plus export format for Gephi / Cytoscape."""

    export_format: Literal["gexf", "graphml"] = Field(default="gexf", description="GEXF (Gephi) or GraphML interchange.")


def _get_case(case_id: str, db: Session) -> Case:
    row = db.query(Case).filter(Case.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row


@router.post("/{case_id}/network/rings")
def post_network_rings(
    case_id: str,
    body: NetworkRingsRequest = NetworkRingsRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    case = _get_case(case_id, db)
    if not case.dataset_path:
        raise HTTPException(status_code=400, detail="Case has no dataset_path; upload a CSV first.")
    return find_fraud_rings(
        case.dataset_path,
        account_column=body.account_column,
        payer_column=body.payer_column,
        payee_column=body.payee_column,
        amount_column=body.amount_column,
    )


@router.post("/{case_id}/network/export")
def post_network_export(
    case_id: str,
    body: NetworkExportRequest = NetworkExportRequest(),
    db: Session = Depends(get_db),
) -> Response:
    case = _get_case(case_id, db)
    if not case.dataset_path:
        raise HTTPException(status_code=400, detail="Case has no dataset_path; upload a CSV first.")
    try:
        data, ext = export_fraud_ring_network(
            case.dataset_path,
            body.export_format,
            account_column=body.account_column,
            payer_column=body.payer_column,
            payee_column=body.payee_column,
            amount_column=body.amount_column,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset file missing on disk.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    fname = f"fraud_ring_{case_id}.{ext}"
    return Response(
        content=data,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
