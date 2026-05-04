"""Tenant-scoped warehouse paths and per-viewer case ACL for cross-case queries."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import duckdb
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.data.warehouse_paths import tenant_warehouse_path
from backend.database.models import Case, CaseShare

# User SQL must not bypass ACL views by qualifying main.* warehouse tables.
_MAIN_WH_BYPASS = re.compile(
    r"\bmain\.(warehouse_events|entity_occurrences|entity_map)\b",
    re.I,
)
_SET_SCHEMA_IN_USER_SQL = re.compile(r"\bset\s+schema\b", re.I)


def warehouse_sql_acl_precheck(sql: str) -> tuple[bool, str]:
    """Reject patterns that would bypass ephemeral-schema ACL views."""
    raw = sql or ""
    if _MAIN_WH_BYPASS.search(raw):
        return (
            False,
            "Do not qualify warehouse tables as main.warehouse_events (or entity_*); "
            "use unqualified names so ACL views apply.",
        )
    if _SET_SCHEMA_IN_USER_SQL.search(raw):
        return False, "SET schema is not allowed in warehouse SQL."
    return True, ""


def tenant_id_for_case(db: Session, case_id: str | None) -> str:
    if not case_id:
        return DEFAULT_TENANT_ID
    row = db.query(Case).filter(Case.id == case_id).first()
    if not row or not getattr(row, "tenant_id", None):
        return DEFAULT_TENANT_ID
    return str(row.tenant_id)


async def tenant_id_for_case_async(db: AsyncSession, case_id: str | None) -> str:
    if not case_id:
        return DEFAULT_TENANT_ID
    r = await db.execute(select(Case.tenant_id).where(Case.id == case_id))
    row = r.one_or_none()
    if not row or row[0] is None:
        return DEFAULT_TENANT_ID
    return str(row[0])


def allowed_source_case_ids(
    db: Session,
    *,
    tenant_id: str,
    viewer_case_id: str | None,
) -> frozenset[str]:
    """
    Cases whose warehouse rows may appear in queries for ``viewer_case_id``.

    Always includes ``viewer_case_id`` when set. Adds ``owner_case_id`` for each
    ``CaseShare`` row where ``viewer_case_id`` is the viewer. If ``viewer_case_id``
    is None, all cases in the tenant are visible (HTTP/admin style).
    """
    q = db.query(Case.id).filter(Case.tenant_id == tenant_id)
    tenant_cases = frozenset(str(r[0]) for r in q.all())
    if not viewer_case_id:
        return tenant_cases
    vid = str(viewer_case_id).strip()
    allowed: set[str] = {vid}
    if vid not in tenant_cases:
        return frozenset(allowed)
    owners = db.query(CaseShare.owner_case_id).filter(CaseShare.viewer_case_id == vid).all()
    for (oid,) in owners:
        if oid and str(oid) in tenant_cases:
            allowed.add(str(oid))
    return frozenset(allowed)


def resolve_tenant_warehouse_path(tenant_id: str) -> Path:
    return Path(tenant_warehouse_path(settings.data_dir, tenant_id))


def _in_list_sql(allowed: frozenset[str]) -> str:
    if not allowed:
        return "NULL"
    parts: list[str] = []
    for x in sorted(allowed):
        s = str(x).replace("'", "''")
        parts.append(f"'{s}'")
    return ", ".join(parts)


def install_warehouse_acl_schema(con: duckdb.DuckDBPyConnection, schema: str, allowed: frozenset[str]) -> None:
    """
    Create a dedicated schema with ACL views that shadow base table names for this connection.

    Caller must ``SET schema = main`` and ``DROP SCHEMA ... CASCADE`` when finished.
    """
    ids_sql = _in_list_sql(allowed)
    con.execute(f"CREATE SCHEMA {schema}")
    if not allowed:
        con.execute(
            f"CREATE VIEW {schema}.warehouse_events AS SELECT * FROM main.warehouse_events WHERE FALSE",
        )
        con.execute(
            f"CREATE VIEW {schema}.entity_occurrences AS SELECT * FROM main.entity_occurrences WHERE FALSE",
        )
        con.execute(f"CREATE VIEW {schema}.entity_map AS SELECT * FROM main.entity_map WHERE FALSE")
    else:
        con.execute(
            f"CREATE VIEW {schema}.warehouse_events AS "
            f"SELECT * FROM main.warehouse_events WHERE source_case_id IN ({ids_sql})",
        )
        con.execute(
            f"CREATE VIEW {schema}.entity_occurrences AS "
            f"SELECT * FROM main.entity_occurrences WHERE source_case_id IN ({ids_sql})",
        )
        con.execute(
            f"CREATE VIEW {schema}.entity_map AS SELECT * FROM main.entity_map em WHERE EXISTS ("
            f"SELECT 1 FROM unnest(em.case_ids) AS _scopes(_cid) WHERE _cid IN ({ids_sql}))",
        )
    con.execute(f"SET schema = {schema}")


def teardown_warehouse_acl_schema(con: duckdb.DuckDBPyConnection, schema: str) -> None:
    """Return to main and drop the ephemeral ACL schema."""
    try:
        con.execute("SET schema = main")
    except Exception:  # noqa: BLE001
        pass
    try:
        con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    except Exception:  # noqa: BLE001
        pass


def new_acl_schema_name() -> str:
    """Unquoted-safe identifier (letters, digits, underscore)."""
    return "whacl_" + uuid.uuid4().hex
