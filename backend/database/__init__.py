"""Persistence layer: SQLAlchemy + DuckDB ingestion utilities."""
from __future__ import annotations

from backend.database.ingestion import IngestionEngine, new_lead_id
from backend.database.models import AuditLog, Case, CaseShare, CaseWorkbenchPins, Lead
from backend.database.session import (
    AsyncSessionLocal,
    Base,
    SessionLocal,
    async_engine,
    engine,
    ensure_sqlite_migrations,
    get_db,
    get_db_sync,
    init_db_schema_async,
)

__all__ = [
    "AsyncSessionLocal",
    "AuditLog",
    "Base",
    "Case",
    "CaseShare",
    "CaseWorkbenchPins",
    "IngestionEngine",
    "Lead",
    "SessionLocal",
    "async_engine",
    "engine",
    "ensure_sqlite_migrations",
    "get_db",
    "get_db_sync",
    "init_db_schema_async",
    "new_lead_id",
]
