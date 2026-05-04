"""Fraud ring / collusion network analysis (graph)."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback_async
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


async def _get_case(case_id: str, db: AsyncSession) -> Case:
    r = await db.execute(select(Case).where(Case.id == case_id))
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row


@router.post("/{case_id}/network/rings")
async def post_network_rings(
    case_id: str,
    body: NetworkRingsRequest = NetworkRingsRequest(),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    case = await _get_case(case_id, db)
    path = await resolve_with_active_fallback_async(db, case.dataset_path)
    if not path:
        raise HTTPException(status_code=400, detail="Case has no dataset_path; upload a CSV first.")
    return await run_in_threadpool(
        find_fraud_rings,
        path,
        account_column=body.account_column,
        payer_column=body.payer_column,
        payee_column=body.payee_column,
        amount_column=body.amount_column,
    )


def _export_network_sync(
    path: str,
    export_format: str,
    account_column: str | None,
    payer_column: str | None,
    payee_column: str | None,
    amount_column: str | None,
    case_id: str,
) -> Response:
    try:
        data, ext = export_fraud_ring_network(
            path,
            export_format,
            account_column=account_column,
            payer_column=payer_column,
            payee_column=payee_column,
            amount_column=amount_column,
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


@router.post("/{case_id}/network/export")
async def post_network_export(
    case_id: str,
    body: NetworkExportRequest = NetworkExportRequest(),
    db: AsyncSession = Depends(get_db),
) -> Response:
    case = await _get_case(case_id, db)
    path = await resolve_with_active_fallback_async(db, case.dataset_path)
    if not path:
        raise HTTPException(status_code=400, detail="Case has no dataset_path; upload a CSV first.")
    return await run_in_threadpool(
        _export_network_sync,
        path,
        body.export_format,
        body.account_column,
        body.payer_column,
        body.payee_column,
        body.amount_column,
        case_id,
    )
