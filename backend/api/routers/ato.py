"""ATO behavioral baseline and session-vs-baseline analysis (DuckDB)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.database.models import Case
from backend.schemas import AtoAnalyzeRequest, AtoKillSessionRequest, AtoUserRequest
from backend.tools.ato_analyzer import analyze_ato_risk
from backend.tools.ato_columns import fetch_column_names, quote_ident, resolve_ato_columns
from backend.tools.audit_log import record_audit
from backend.tools.user_profiler import build_user_behavioral_profile

router = APIRouter(prefix="/api/cases", tags=["ato"])


def _get_case(case_id: str, db: Session) -> Case:
    row = db.query(Case).filter(Case.id == case_id).first()
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
def ato_profile(case_id: str, body: AtoUserRequest, db: Session = Depends(get_db)) -> dict:
    """Behavioral DNA baseline for a user from historical rows."""
    case = _get_case(case_id, db)
    duck = _duckdb_or_400(case)
    return build_user_behavioral_profile(
        duck,
        body.user_id,
        user_column=body.user_column,
    )


@router.post("/{case_id}/ato/analyze")
def ato_analyze(case_id: str, body: AtoAnalyzeRequest, db: Session = Depends(get_db)) -> dict:
    """Compare current_session to DuckDB baseline; returns flags + discrepancies."""
    case = _get_case(case_id, db)
    duck = _duckdb_or_400(case)
    uid = (body.user_id or "").strip()
    return analyze_ato_risk(
        duck,
        uid,
        body.current_session,
        user_column=body.user_column,
    )


@router.get("/{case_id}/ato/user-id-samples")
def ato_user_id_samples(
    case_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(40, ge=1, le=200),
) -> dict:
    """Distinct account / user ids from the case DuckDB for quick-pick UX."""
    import duckdb as ddb

    from backend.database.ingestion import _configure_duckdb

    case = _get_case(case_id, db)
    duck = _duckdb_or_400(case)
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


@router.post("/{case_id}/ato/kill-session")
def ato_kill_session(case_id: str, body: AtoKillSessionRequest, db: Session = Depends(get_db)) -> dict:
    """SOC stub: records revocation intent; wire to your IdP/token service for production."""
    _get_case(case_id, db)
    payload = body.model_dump()
    record_audit(
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
