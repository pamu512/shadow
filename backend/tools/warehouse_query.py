"""Read-only queries against the Global Warehouse DuckDB (no user file requests)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb

from backend.config import settings
from backend.database.ingestion import _configure_duckdb

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|copy|pragma|export|import|"
    r"create|replace|truncate|call|checkpoint|rollback|commit|vacuum)\b",
    re.I,
)
_MAX_SQL_LEN = 12_000
_MAX_ROWS = 500


def validate_readonly_select(sql: str) -> tuple[bool, str]:
    raw = (sql or "").strip()
    if not raw:
        return False, "Empty SQL."
    if len(raw) > _MAX_SQL_LEN:
        return False, f"Query exceeds max length ({_MAX_SQL_LEN})."
    low = raw.lower()
    if not low.startswith(("select", "with")):
        return False, "Only SELECT or WITH ... SELECT queries are allowed."
    stripped = raw.rstrip().rstrip(";")
    if ";" in stripped:
        return False, "Multiple statements are not allowed (single SELECT/WITH only)."
    if _FORBIDDEN.search(low):
        return False, "Forbidden DDL/DML keywords detected in query."
    if "--" in raw or "/*" in raw:
        return False, "SQL comments are not allowed; use a plain SELECT."
    return True, ""


def run_warehouse_query(sql: str) -> dict[str, Any]:
    """Execute one read-only SELECT against the global warehouse."""
    ok, err = validate_readonly_select(sql)
    if not ok:
        return {"ok": False, "error": err, "kind": "warehouse_query"}
    path = Path(settings.global_warehouse_db_path)
    if not path.is_file():
        return {
            "ok": False,
            "error": "Global warehouse not initialized (no database file yet).",
            "kind": "warehouse_query",
        }
    con = duckdb.connect(str(path), read_only=True)
    try:
        _configure_duckdb(con)
        cur = con.execute(sql)
        desc = cur.description or []
        columns = [d[0] for d in desc]
        rows = cur.fetchmany(_MAX_ROWS + 1)
        truncated = len(rows) > _MAX_ROWS
        data = rows[:_MAX_ROWS]
        serializable: list[dict[str, Any]] = []
        for tup in data:
            row_dict: dict[str, Any] = {}
            for i, col in enumerate(columns):
                v = tup[i] if i < len(tup) else None
                if hasattr(v, "isoformat"):
                    row_dict[col] = v.isoformat()
                else:
                    row_dict[col] = v
            serializable.append(row_dict)
        return {
            "ok": True,
            "columns": columns,
            "rows": serializable,
            "row_count": len(serializable),
            "truncated": truncated,
            "kind": "warehouse_query",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "kind": "warehouse_query"}
    finally:
        con.close()


def run_warehouse_text_search(needle: str, *, limit: int = 40) -> dict[str, Any]:
    """ILIKE search across row_json and source_filename (stress-test / tag discovery)."""
    n = (needle or "").strip()[:256]
    if len(n) < 2:
        return {"ok": False, "error": "needle must be at least 2 characters.", "kind": "warehouse_text_search"}
    lim = max(1, min(int(limit or 40), 200))
    path = Path(settings.global_warehouse_db_path)
    if not path.is_file():
        return {
            "ok": False,
            "error": "Global warehouse not initialized (no database file yet).",
            "kind": "warehouse_text_search",
        }
    pattern = f"%{n}%"
    sql = """
        SELECT DISTINCT
            source_case_id,
            source_filename,
            upload_timestamp
        FROM warehouse_events
        WHERE lower(row_json) LIKE lower(?)
           OR lower(coalesce(source_filename, '')) LIKE lower(?)
        ORDER BY upload_timestamp ASC
        LIMIT ?
    """
    return _run_parameterized(path, sql, [pattern, pattern, lim], kind="warehouse_text_search", needle=n)


def _run_parameterized(
    path: Path,
    sql: str,
    params: list[Any],
    *,
    kind: str,
    needle: str | None = None,
) -> dict[str, Any]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        _configure_duckdb(con)
        cur = con.execute(sql, params)
        desc = cur.description or []
        columns = [d[0] for d in desc]
        rows = cur.fetchall()
        serializable: list[dict[str, Any]] = []
        for tup in rows:
            row_dict: dict[str, Any] = {}
            for i, col in enumerate(columns):
                v = tup[i] if i < len(tup) else None
                if hasattr(v, "isoformat"):
                    row_dict[col] = v.isoformat()
                else:
                    row_dict[col] = v
            serializable.append(row_dict)
        out: dict[str, Any] = {
            "ok": True,
            "columns": columns,
            "rows": serializable,
            "row_count": len(serializable),
            "kind": kind,
        }
        if needle is not None:
            out["needle"] = needle
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "kind": kind}
    finally:
        con.close()
