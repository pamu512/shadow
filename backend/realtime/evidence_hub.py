"""Push lead events to connected Evidence Board clients (WebSocket)."""
from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

_PENDING: list[tuple[str, dict[str, Any]]] = []
_PENDING_LOCK = threading.Lock()


def push_lead_event(case_id: str, payload: dict[str, Any]) -> None:
    """Thread-safe enqueue; consumed by the async pump in app lifespan."""
    with _PENDING_LOCK:
        _PENDING.append((case_id, dict(payload)))


def drain_lead_events() -> list[tuple[str, dict[str, Any]]]:
    with _PENDING_LOCK:
        out = _PENDING[:]
        _PENDING.clear()
        return out


class EvidenceHub:
    """One room per case_id."""

    def __init__(self) -> None:
        self._rooms: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, case_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._rooms[case_id].append(ws)

    async def disconnect(self, case_id: str, ws: WebSocket) -> None:
        lst = self._rooms.get(case_id)
        if not lst:
            return
        if ws in lst:
            lst.remove(ws)

    async def broadcast(self, case_id: str, message: dict[str, Any]) -> None:
        targets = list(self._rooms.get(case_id, []))
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                await self.disconnect(case_id, ws)


async def run_evidence_event_pump(hub: EvidenceHub) -> None:
    while True:
        await asyncio.sleep(0.1)
        for case_id, msg in drain_lead_events():
            await hub.broadcast(case_id, msg)
