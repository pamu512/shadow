"""Persistence layer: SQLAlchemy + DuckDB ingestion utilities."""
from __future__ import annotations

from backend.database.ingestion import IngestionEngine, new_lead_id
from backend.database.models import AuditLog, Case, Lead
from backend.database.session import Base, SessionLocal, engine, ensure_sqlite_migrations, get_db

__all__ = [
    "AuditLog",
    "Base",
    "Case",
    "IngestionEngine",
    "Lead",
    "SessionLocal",
    "engine",
    "ensure_sqlite_migrations",
    "get_db",
    "new_lead_id",
]
