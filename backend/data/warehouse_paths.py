"""Filesystem layout for per-tenant warehouse DuckDB (no ORM / settings cycles)."""
from __future__ import annotations

import re
from pathlib import Path

from backend.data.tenant_constants import DEFAULT_TENANT_ID


def tenant_warehouse_path(data_dir: Path, tenant_id: str) -> Path:
    tid = (tenant_id or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", tid)[:128]
    p = Path(data_dir) / "warehouse" / safe / "warehouse.duckdb"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
