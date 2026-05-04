"""ATO behavioral baseline and session-vs-baseline analysis (DuckDB)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.database import get_db
from backend.database.models import Case
from backend.schemas import AtoAnalyzeRequest, AtoKillSessionRequest, AtoUserRequest
from backend.tools.ato_analyzer import analyze_ato_risk
from backend.tools.ato_columns import fetch_column_names, quote_ident, resolve_ato_columns
from backend.tools.audit_log import record_audit_async
from backend.tools.user_profiler import build_user_behavioral_profile

router = APIRouter(prefix="/api/cases", tags=["ato"])


async def _get_case(case_id: str, db: AsyncSession) -> Case:
    r = await db.execute(select(Case).where(Case.id == case_id))
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row


def _duckdb_or_400(case: Case) -> str:
    if not case.duckdb_path:
        raise HTTPException(
            status_code=400,
            detail="Case has no DuckDB store; upload/ingest a CSV first.",
        )
    return case.duckdb_path


@router.post("/{case_id}/ato/profile")
async def ato_profile(case_id: str, body: AtoUserRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Behavioral DNA baseline for a user from historical rows."""
    case = await _get_case(case_id, db)
    duck = _duckdb_or_400(case)
    return await run_in_threadpool(
        build_user_behavioral_profile,
        duck,
        body.user_id,
        user_column=body.user_column,
    )


@router.post("/{case_id}/ato/analyze")
async def ato_analyze(case_id: str, body: AtoAnalyzeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Compare current_session to DuckDB baseline; returns flags + discrepancies."""
    case = await _get_case(case_id, db)
    duck = _duckdb_or_400(case)
    uid = (body.user_id or "").strip()
    return await run_in_threadpool(
        analyze_ato_risk,
        duck,
        uid,
        body.current_session,
        user_column=body.user_column,
    )


def _ato_user_id_samples_sync(duck: str, limit: int) -> dict:
    import duckdb as ddb

    from backend.database.ingestion import _configure_duckdb

    con = ddb.connect(str(duck), read_only=True)
    try:
        try:
            _configure_duckdb(con)
        except Exception:  # noqa: BLE001
            pass
        cols = resolve_ato_columns(con, "dataset")
        col = cols.get("user_id")
        names = fetch_column_names(con, "dataset")
        if not col or col not in names:
            return {
                "ok": False,
                "error": "Could not resolve user / account id column.",
                "user_ids": [],
                "column": None,
                "columns": names,
            }
        uq, tq = quote_ident(col), quote_ident("dataset")
        rows = con.sql(
            f"""
            SELECT CAST({uq} AS VARCHAR) AS uid, COUNT(*) AS n
            FROM {tq}
            WHERE {uq} IS NOT NULL AND TRIM(CAST({uq} AS VARCHAR)) <> ''
            GROUP BY 1
            ORDER BY n DESC
            LIMIT {int(limit)}
            """,
        ).fetchall()
        pairs = [{"user_id": str(r[0]), "row_count": int(r[1])} for r in rows if r and r[0]]
        return {"ok": True, "column": col, "user_ids": [p["user_id"] for p in pairs], "samples": pairs}
    finally:
        con.close()


@router.get("/{case_id}/ato/user-id-samples")
async def ato_user_id_samples(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(40, ge=1, le=200),
) -> dict:
    """Distinct account / user ids from the case DuckDB for quick-pick UX."""
    case = await _get_case(case_id, db)
    duck = _duckdb_or_400(case)
    return await run_in_threadpool(_ato_user_id_samples_sync, duck, limit)


@router.post("/{case_id}/ato/kill-session")
async def ato_kill_session(case_id: str, body: AtoKillSessionRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """SOC stub: records revocation intent; wire to your IdP/token service for production."""
    await _get_case(case_id, db)
    payload = body.model_dump()
    await record_audit_async(
        db,
        case_id=case_id,
        action_taken="ATO_KILL_SESSION",
        code_executed=json.dumps(payload, default=str)[:8000],
        agent_notes="Operator requested session invalidation from ATO Session Comparison UI.",
    )
    return {
        "ok": True,
        "message": "Kill-session command logged. Add IdP / session-revocation integration to enforce tokens.",
    }
