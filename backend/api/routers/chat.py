"""Chat -> LangGraph."""
from __future__ import annotations

import logging
import sys
import traceback

import httpx
from fastapi import APIRouter, Depends, HTTPException
from openai import APIConnectionError, APITimeoutError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.agent.coordinator import build_persona_suggestion, resolve_persona_id
from backend.agent.runner import invoke_chat
from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback_async
from backend.database.models import Case
from backend.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)

_LLM_UNREACHABLE_TYPES: tuple[type[BaseException], ...] = (
    APIConnectionError,
    APITimeoutError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)


def _is_llm_unreachable(exc: BaseException) -> bool:
    """True if exc or any nested cause/group member is a transport failure to the LLM."""
    stack: list[BaseException] = [exc]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        i = id(cur)
        if i in seen:
            continue
        seen.add(i)
        if isinstance(cur, _LLM_UNREACHABLE_TYPES):
            return True
        if isinstance(cur, BaseExceptionGroup):
            stack.extend(cur.exceptions)
        if cur.__cause__ is not None:
            stack.append(cur.__cause__)
        if cur.__context__ is not None and cur.__context__ is not cur.__cause__:
            stack.append(cur.__context__)
    return False


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    ds_path = None
    duck_path = None
    schema_summary = None
    cid = body.case_id
    if cid:
        r = await db.execute(select(Case).where(Case.id == cid))
        c = r.scalar_one_or_none()
        if c:
            ds_path = c.dataset_path
            duck_path = c.duckdb_path
            if isinstance(c.schema_summary, dict):
                schema_summary = c.schema_summary
    else:
        ar = await db.execute(select(Case).where(Case.is_active.is_(True)).limit(1))
        active = ar.scalar_one_or_none()
        if active:
            cid = active.id
            ds_path = active.dataset_path
            duck_path = active.duckdb_path
            if isinstance(active.schema_summary, dict):
                schema_summary = active.schema_summary
    ds_path = await resolve_with_active_fallback_async(db, ds_path)
    persona_id = resolve_persona_id(body.persona_id)
    try:
        msgs, dbg = await run_in_threadpool(
            invoke_chat,
            body.messages,
            case_id=cid,
            dataset_path=ds_path,
            duckdb_path=duck_path,
            persona_id=body.persona_id,
            thread_reset=body.thread_reset,
            thread_id=body.thread_id,
        )  # type: ignore[misc]
        suggestion = build_persona_suggestion(schema_summary)
    except Exception as e:
        if _is_llm_unreachable(e):
            logger.warning("LLM unreachable during chat: %s", e)
            raise HTTPException(
                status_code=503,
                detail=(
                    "Cannot reach the configured LLM (Ollama or OpenAI-compatible API). "
                    "Start Ollama, check Preferences → model host, or set SHADOW_OLLAMA_BASE_URL."
                ),
            ) from e
        logger.exception("Chat invoke failed")
        print(f"ERROR backend.api.routers.chat: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        msg = str(e).strip() or type(e).__name__
        raise HTTPException(status_code=500, detail=msg[:2000]) from e
    return ChatResponse(
        messages=msgs,
        debug=dbg,
        persona_id=persona_id,
        persona_suggestion=suggestion,
    )
