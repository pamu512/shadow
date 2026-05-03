"""SQLAlchemy engine, session, and SQLite migrations."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.case_status import DEFAULT_CASE_STATUS, normalize_case_status
from backend.config import settings


class Base(DeclarativeBase):
    pass


def _sqlite_connect_args() -> dict:
    return {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}


engine = create_engine(settings.database_url, connect_args=_sqlite_connect_args())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _connection_record) -> None:
    if settings.database_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_sqlite_migrations() -> None:
    """Add columns / normalize data for older SQLite files."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        tbl = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='cases'")
        ).fetchone()
        if not tbl:
            return
        rows = conn.execute(text("PRAGMA table_info(cases)")).fetchall()
        col_names = {r[1] for r in rows}
        if "status" not in col_names:
            conn.execute(
                text(
                    f"ALTER TABLE cases ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT '{DEFAULT_CASE_STATUS}'"
                )
            )
        else:
            conn.execute(
                text("UPDATE cases SET status = :st WHERE status IS NULL OR TRIM(status) = ''"),
                {"st": DEFAULT_CASE_STATUS},
            )
        raw = conn.execute(text("SELECT id, status FROM cases")).fetchall()
        for cid, st in raw:
            norm = normalize_case_status(st)
            if norm != st:
                conn.execute(text("UPDATE cases SET status = :s WHERE id = :i"), {"s": norm, "i": cid})

        rows = conn.execute(text("PRAGMA table_info(cases)")).fetchall()
        col_names = {r[1] for r in rows}
        if "updated_at" not in col_names:
            conn.execute(text("ALTER TABLE cases ADD COLUMN updated_at DATETIME"))
        if "duckdb_path" not in col_names:
            conn.execute(text("ALTER TABLE cases ADD COLUMN duckdb_path VARCHAR(1024)"))
        if "schema_summary" not in col_names:
            conn.execute(text("ALTER TABLE cases ADD COLUMN schema_summary JSON"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS case_workbench_pins (
                    case_id VARCHAR(36) PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
                    pins_json JSON NOT NULL,
                    updated_at DATETIME
                )
                """
            )
        )

        conn.execute(text("UPDATE leads SET status = 'DISMISSED' WHERE status = 'CLOSED'"))

        rows = conn.execute(text("PRAGMA table_info(cases)")).fetchall()
        col_names = {r[1] for r in rows}
        if "tenant_id" not in col_names:
            conn.execute(text("ALTER TABLE cases ADD COLUMN tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS case_shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_case_id VARCHAR(36) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    viewer_case_id VARCHAR(36) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                    UNIQUE(owner_case_id, viewer_case_id)
                )
                """
            )
        )
