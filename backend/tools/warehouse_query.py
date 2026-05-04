"""Read-only queries against the tenant-scoped Global Warehouse DuckDB (no user file requests)."""
from __future__ import annotations

import contextvars
import re
from pathlib import Path
from typing import Any

import duckdb

from backend.config import settings
from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.data.warehouse_access import (
    allowed_source_case_ids,
    install_warehouse_acl_schema,
    new_acl_schema_name,
    resolve_tenant_warehouse_path,
    teardown_warehouse_acl_schema,
    warehouse_sql_acl_precheck,
)
from backend.database.duckdb_lock import duckdb_lock_path
from backend.database.ingestion import _configure_duckdb
from backend.database.session import SessionLocal

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|copy|pragma|export|import|"
    r"create|replace|truncate|call|checkpoint|rollback|commit|vacuum)\b",
    re.I,
)
_MAX_SQL_LEN = 12_000
_MAX_ROWS = 500

_warehouse_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar("wh_tenant", default=None)
_warehouse_viewer: contextvars.ContextVar[str | None] = contextvars.ContextVar("wh_viewer", default=None)


def set_warehouse_query_context(*, tenant_id: str | None, viewer_case_id: str | None) -> None:
    """Bound for the duration of an agent chat turn (tenant + active case for ACL)."""
    _warehouse_tenant.set(tenant_id)
    _warehouse_viewer.set(viewer_case_id)


def clear_warehouse_query_context() -> None:
    _warehouse_tenant.set(None)
    _warehouse_viewer.set(None)


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
    ok_acl, err_acl = warehouse_sql_acl_precheck(raw)
    if not ok_acl:
        return False, err_acl
    return True, ""


def _resolve_scope(
    *,
    tenant_id: str | None,
    viewer_case_id: str | None,
) -> tuple[str, frozenset[str]]:
    tid = (tenant_id or _warehouse_tenant.get() or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
    viewer = viewer_case_id if viewer_case_id is not None else _warehouse_viewer.get()
    db = SessionLocal()
    try:
        allowed = allowed_source_case_ids(db, tenant_id=tid, viewer_case_id=viewer)
    finally:
        db.close()
    return tid, allowed


def run_warehouse_query(
    sql: str,
    *,
    tenant_id: str | None = None,
    viewer_case_id: str | None = None,
) -> dict[str, Any]:
    """Execute one read-only SELECT against the tenant warehouse with case-level ACL."""
    ok, err = validate_readonly_select(sql)
    if not ok:
        return {"ok": False, "error": err, "kind": "warehouse_query"}
    tid, allowed = _resolve_scope(tenant_id=tenant_id, viewer_case_id=viewer_case_id)
    path = resolve_tenant_warehouse_path(tid)
    if not path.is_file():
        return {
            "ok": False,
            "error": "Tenant warehouse not initialized (no database file yet).",
            "kind": "warehouse_query",
        }
    schema = new_acl_schema_name()
    with duckdb_lock_path(path):
        con = duckdb.connect(str(path), read_only=False)
        try:
            _configure_duckdb(con)
            install_warehouse_acl_schema(con, schema, allowed)
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
            teardown_warehouse_acl_schema(con, schema)
            con.close()


def run_warehouse_text_search(
    needle: str,
    *,
    limit: int = 40,
    tenant_id: str | None = None,
    viewer_case_id: str | None = None,
) -> dict[str, Any]:
    """ILIKE search across row_json and source_filename (stress-test / tag discovery)."""
    n = (needle or "").strip()[:256]
    if len(n) < 2:
        return {"ok": False, "error": "needle must be at least 2 characters.", "kind": "warehouse_text_search"}
    lim = max(1, min(int(limit or 40), 200))
    tid, allowed = _resolve_scope(tenant_id=tenant_id, viewer_case_id=viewer_case_id)
    path = resolve_tenant_warehouse_path(tid)
    if not path.is_file():
        return {
            "ok": False,
            "error": "Tenant warehouse not initialized (no database file yet).",
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
    return _run_parameterized(
        path,
        sql,
        [pattern, pattern, lim],
        allowed,
        kind="warehouse_text_search",
        needle=n,
    )


def _run_parameterized(
    path: Path,
    sql: str,
    params: list[Any],
    allowed: frozenset[str],
    *,
    kind: str,
    needle: str | None = None,
) -> dict[str, Any]:
    schema = new_acl_schema_name()
    with duckdb_lock_path(path):
        con = duckdb.connect(str(path), read_only=False)
        try:
            _configure_duckdb(con)
            install_warehouse_acl_schema(con, schema, allowed)
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
            teardown_warehouse_acl_schema(con, schema)
            con.close()
