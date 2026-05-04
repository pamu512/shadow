"""Agent-facing analytical APIs (DuckDB)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import IngestionEngine, get_db
from backend.database.models import Case
from backend.schemas import AgentQueryRequest, AgentQueryResponse
from backend.tools.audit_log import record_audit_async

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/query", response_model=AgentQueryResponse)
async def agent_query(body: AgentQueryRequest, db: AsyncSession = Depends(get_db)) -> AgentQueryResponse:
    r = await db.execute(select(Case).where(Case.id == body.case_id))
    case = r.scalar_one_or_none()
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
    await record_audit_async(
        db,
        case_id=case.id,
        action_taken="DuckDB agent query",
        code_executed=body.sql,
        agent_notes=f"{resp.row_count} rows × {len(resp.columns)} columns",
    )
    return resp
