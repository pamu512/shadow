"""Agent-facing analytical APIs (DuckDB)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import IngestionEngine, get_db
from backend.database.models import Case
from backend.schemas import AgentQueryRequest, AgentQueryResponse
from backend.tools.audit_log import record_audit

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/query", response_model=AgentQueryResponse)
def agent_query(body: AgentQueryRequest, db: Session = Depends(get_db)) -> AgentQueryResponse:
    case = db.query(Case).filter(Case.id == body.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    if not case.duckdb_path:
        raise HTTPException(400, "Case has no analytical store; upload a CSV first.")
    engine = IngestionEngine()
    try:
        cols, rows = engine.run_select(case.id, body.sql)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Query error: {e}") from e
    resp = AgentQueryResponse(columns=cols, rows=rows, row_count=len(rows))
    record_audit(
        db,
        case_id=case.id,
        action_taken="DuckDB agent query",
        code_executed=body.sql,
        agent_notes=f"{resp.row_count} rows × {len(resp.columns)} columns",
    )
    return resp
