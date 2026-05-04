"""LangGraph checkpointer: PostgreSQL when ``SHADOW_DATABASE_URL`` is Postgres, else SQLite under ``.data``."""
from __future__ import annotations

import threading

from backend.config import settings

_lock = threading.Lock()
_ctx: object | None = None
_saver: object | None = None
_pg_conn: object | None = None


def _is_postgres_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("postgres")


def _normalize_psycopg_dsn(url: str) -> str:
    u = url.strip()
    for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql+asyncpg://"):
        if u.lower().startswith(prefix.lower()):
            rest = u.split("://", 1)[1]
            return f"postgresql://{rest}"
    return u


def get_langgraph_checkpointer():
    """Singleton saver (SQLite file or Postgres connection)."""
    global _ctx, _saver, _pg_conn
    with _lock:
        if _saver is not None:
            return _saver
        if _is_postgres_url(settings.database_url):
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg import Connection
            from psycopg.rows import dict_row

            dsn = _normalize_psycopg_dsn(settings.database_url)
            _pg_conn = Connection.connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row)
            _saver = PostgresSaver(_pg_conn)
            _saver.setup()
        else:
            from langgraph.checkpoint.sqlite import SqliteSaver

            path = (settings.data_dir / "langgraph_checkpoints.sqlite").resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            _ctx = SqliteSaver.from_conn_string(str(path))
            _saver = _ctx.__enter__()
        return _saver
