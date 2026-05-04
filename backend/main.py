"""FastAPI entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import (
    agent,
    ato,
    bots,
    cases,
    chargeback,
    chat,
    code_review,
    execute,
    health,
    network,
    personas,
    scaffold,
    thresholds,
    warehouse,
)
from backend.database import init_db_schema_async
from backend.rag.knowledge_store import ensure_ingested
from backend.realtime.evidence_hub import EvidenceHub, run_evidence_event_pump


def _ensure_backend_logging() -> None:
    """Attach a stderr handler so router `logger.exception` lines appear beside uvicorn access logs."""
    log = logging.getLogger("backend")
    if log.handlers:
        return
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    log.setLevel(logging.INFO)
    log.addHandler(h)
    log.propagate = False


_ensure_backend_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_schema_async()
    hub = EvidenceHub()
    app.state.evidence_hub = hub
    pump = asyncio.create_task(run_evidence_event_pump(hub))
    try:
        ensure_ingested()
        yield
    finally:
        pump.cancel()
        try:
            await pump
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Shadow Sidecar", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(cases.router)
app.include_router(ato.router)
app.include_router(bots.router)
app.include_router(network.router)
app.include_router(chargeback.router)
app.include_router(agent.router)
app.include_router(personas.router)
app.include_router(chat.router)
app.include_router(code_review.router)
app.include_router(execute.router)
app.include_router(thresholds.router)
app.include_router(scaffold.router)
app.include_router(warehouse.router)


@app.websocket("/ws/cases/{case_id}/evidence")
async def evidence_board_ws(websocket: WebSocket, case_id: str) -> None:
    hub: EvidenceHub = websocket.app.state.evidence_hub
    await hub.connect(case_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(case_id, websocket)
