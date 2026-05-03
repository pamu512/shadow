"""Tenant-scoped warehouse paths and per-viewer case ACL for cross-case queries."""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.data.warehouse_paths import tenant_warehouse_path
from backend.database.models import Case, CaseShare


def tenant_id_for_case(db: Session, case_id: str | None) -> str:
    if not case_id:
        return DEFAULT_TENANT_ID
    row = db.query(Case).filter(Case.id == case_id).first()
    if not row or not getattr(row, "tenant_id", None):
        return DEFAULT_TENANT_ID
    return str(row.tenant_id)


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


def scope_warehouse_sql(sql: str, allowed: frozenset[str]) -> str:
    """
    Rewrite base table references so rows are limited to ``allowed`` ``source_case_id`` / ``case_ids``.

    ``entity_map`` is filtered with ``list_has_any(case_ids, ARRAY[...])``.
    """
    if not allowed:
        empty_we = "(SELECT * FROM warehouse_events WHERE FALSE)"
        empty_eo = "(SELECT * FROM entity_occurrences WHERE FALSE)"
        empty_em = "(SELECT * FROM entity_map WHERE FALSE)"
        out = re.sub(r"\bwarehouse_events\b", empty_we, sql, flags=re.IGNORECASE)
        out = re.sub(r"\bentity_occurrences\b", empty_eo, out, flags=re.IGNORECASE)
        out = re.sub(r"\bentity_map\b", empty_em, out, flags=re.IGNORECASE)
        return out
    ids_sql = ", ".join(f"'{str(x).replace(chr(39), chr(39)+chr(39))}'" for x in sorted(allowed))

    def repl_events(m: re.Match[str]) -> str:
        return f"(SELECT * FROM warehouse_events WHERE source_case_id IN ({ids_sql}))"

    def repl_occ(m: re.Match[str]) -> str:
        return f"(SELECT * FROM entity_occurrences WHERE source_case_id IN ({ids_sql}))"

    def repl_map(m: re.Match[str]) -> str:
        return (
            "(SELECT * FROM entity_map em WHERE EXISTS ("
            "SELECT 1 FROM unnest(em.case_ids) AS _scopes(_cid) "
            f"WHERE _cid IN ({ids_sql})))"
        )

    out = sql
    out = re.sub(r"\bwarehouse_events\b", repl_events, out, flags=re.IGNORECASE)
    out = re.sub(r"\bentity_occurrences\b", repl_occ, out, flags=re.IGNORECASE)
    out = re.sub(r"\bentity_map\b", repl_map, out, flags=re.IGNORECASE)
    return out
