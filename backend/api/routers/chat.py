"""Chat -> LangGraph."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.agent.coordinator import build_persona_suggestion, resolve_persona_id
from backend.agent.runner import invoke_chat
from backend.database import get_db
from backend.database.models import Case
from backend.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    ds_path = None
    duck_path = None
    schema_summary = None
    cid = body.case_id
    if cid:
        c = db.query(Case).filter(Case.id == cid).first()
        if c:
            ds_path = c.dataset_path
            duck_path = c.duckdb_path
            if isinstance(c.schema_summary, dict):
                schema_summary = c.schema_summary
    else:
        active = db.query(Case).filter(Case.is_active.is_(True)).first()
        if active:
            cid = active.id
            ds_path = active.dataset_path
            duck_path = active.duckdb_path
            if isinstance(active.schema_summary, dict):
                schema_summary = active.schema_summary
    persona_id = resolve_persona_id(body.persona_id)
    msgs, dbg = invoke_chat(
        body.messages,
        case_id=cid,
        dataset_path=ds_path,
        duckdb_path=duck_path,
        persona_id=body.persona_id,
        thread_reset=body.thread_reset,
    )
    suggestion = build_persona_suggestion(schema_summary)
    return ChatResponse(
        messages=msgs,
        debug=dbg,
        persona_id=persona_id,
        persona_suggestion=suggestion,
    )
