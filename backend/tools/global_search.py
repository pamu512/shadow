"""Cross-case entity overlap search against the global DuckDB warehouse."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from backend.config import settings
from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.data.warehouse import GlobalWarehouse
from backend.data.warehouse_access import allowed_source_case_ids, tenant_id_for_case
from backend.data.warehouse_paths import tenant_warehouse_path
from backend.database.duckdb_lock import duckdb_lock_path
from backend.database.models import Case
from backend.database.session import SessionLocal
from backend.tools.entity_columns import extract_entities_from_row

_STATUS_LABEL: dict[str, str] = {
    "FLAGGED": "Fraud Confirmed",
    "INVESTIGATING": "Under Investigation",
    "CLEARED": "Cleared",
}


def _normalize_entity_type(entity_type: str) -> str | None:
    t = (entity_type or "").strip().lower().replace("-", "_")
    aliases = {
        "user": "user_id",
        "userid": "user_id",
        "account": "user_id",
        "ip": "ip_address",
        "device": "device_id",
        "card": "card_hash",
        "hash": "card_hash",
    }
    t = aliases.get(t, t)
    if t in ("user_id", "ip_address", "device_id", "card_hash"):
        return t
    return None


def _month_year_label(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        from datetime import datetime

        s = str(iso).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d.strftime("%b %Y")
    except Exception:  # noqa: BLE001
        return str(iso)[:10] if iso else "—"


def _build_global_linkage(
    *,
    entity_id: str,
    entity_type: str,
    exclude_case_id: str,
    other_cases: list[dict[str, Any]],
    active_meta: dict[str, Any],
) -> dict[str, Any]:
    """Structured UI: chronological timeline + force-graph edges (historical ↔ focal entity ↔ current)."""
    sorted_hist = sorted(
        [dict(x) for x in other_cases],
        key=lambda x: (x.get("created_at") or x.get("first_seen_in_warehouse") or ""),
    )
    timeline: list[dict[str, Any]] = []
    for oc in sorted_hist:
        name = str(oc.get("case_name") or oc.get("case_id") or "Case")
        theme = "bot_activity" if "bot" in name.lower() else "prior_case"
        timeline.append(
            {
                "case_id": oc.get("case_id"),
                "title": name,
                "month_label": _month_year_label(oc.get("created_at")),
                "position": "historical",
                "theme": theme,
                "result_label": oc.get("result_label"),
            },
        )
    ex = (exclude_case_id or "").strip()
    if ex:
        timeline.append(
            {
                "case_id": ex,
                "title": str(active_meta.get("case_name") or "Active investigation"),
                "month_label": _month_year_label(active_meta.get("created_at")),
                "position": "current",
                "theme": "active_investigation",
                "result_label": active_meta.get("result_label") or "Active",
            },
        )
    else:
        timeline.append(
            {
                "case_id": None,
                "title": "Current investigation",
                "month_label": "Now",
                "position": "current",
                "theme": "active_investigation",
                "result_label": "In context",
            },
        )

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    hist_nids: list[str] = []
    for i, oc in enumerate(sorted_hist):
        cid = str(oc.get("case_id") or f"h{i}")
        nid = f"hist:{cid}"
        hist_nids.append(nid)
        nm = str(oc.get("case_name") or cid)[:56]
        botish = "bot" in nm.lower()
        nodes.append(
            {
                "id": nid,
                "label": nm,
                "type": "historical_case",
                "role": "historical",
                "device_label": "Historical bot activity" if botish else "Prior case overlap",
            },
        )
    cur_nid = "active:case"
    cur_label = str(active_meta.get("case_name") or "This case")[:56] if ex else "This investigation"
    nodes.append(
        {
            "id": cur_nid,
            "label": cur_label,
            "type": "active_case",
            "role": "current",
            "glow": True,
            "device_label": "Current transaction / focal case",
        },
    )
    elab = entity_id if len(entity_id) <= 40 else entity_id[:37] + "…"
    focal = "focal:entity"
    nodes.append(
        {
            "id": focal,
            "label": f"{entity_type}: {elab}",
            "type": "shared_entity",
            "role": "focal",
        },
    )
    for nid in hist_nids:
        links.append(
            {
                "source": nid,
                "target": focal,
                "kind": "shared_entity",
                "color": "rgba(245, 158, 11, 0.72)",
            },
        )
    links.append(
        {
            "source": focal,
            "target": cur_nid,
            "kind": "current_txn",
            "color": "rgba(34, 211, 238, 0.85)",
        },
    )

    et_label = {
        "ip_address": "IP",
        "device_id": "Device",
        "user_id": "User ID",
        "card_hash": "Card hash",
    }.get(entity_type, entity_type.replace("_", " ").title())
    highlight = "amber" if entity_type in ("ip_address", "device_id") else "zinc"
    shared_attributes: list[dict[str, Any]] = [
        {"key": et_label, "value": entity_id, "highlight": highlight},
    ]
    relationship_path: list[dict[str, str]] = []
    for oc in sorted_hist:
        relationship_path.append(
            {
                "role": "historical",
                "title": str(oc.get("case_name") or oc.get("case_id") or "Historical case"),
                "subtitle": "Infrastructure overlap — prior investigation",
            },
        )
    relationship_path.append(
        {
            "role": "bridge",
            "title": f"Shared signal — {et_label}",
            "subtitle": entity_id[:120] + ("" if len(entity_id) <= 120 else "…"),
        },
    )
    cur_title = str(active_meta.get("case_name") or "Active investigation") if ex else "Current investigation"
    relationship_path.append(
        {
            "role": "current",
            "title": cur_title,
            "subtitle": "Entity recidivism touchpoint — active case",
        },
    )

    return {
        "timeline": timeline,
        "graph_data": {"nodes": nodes, "links": links},
        "entity_id": entity_id,
        "entity_type": entity_type,
        "relationship_path": relationship_path,
        "shared_attributes": shared_attributes,
    }


def _case_meta(case_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not case_ids:
        return {}
    db = SessionLocal()
    try:
        rows = db.query(Case).filter(Case.id.in_(case_ids)).all()
        return {
            c.id: {
                "case_id": c.id,
                "case_name": c.name,
                "status": c.status,
                "result_label": _STATUS_LABEL.get(str(c.status or "").upper(), str(c.status or "UNKNOWN")),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        }
    finally:
        db.close()


def search_historical_overlap(
    entity_id: str,
    entity_type: str,
    *,
    exclude_case_id: str | None = None,
    tenant_id: str | None = None,
    viewer_case_id: str | None = None,
) -> dict[str, Any]:
    """
    Look up ``entity_id`` in the warehouse ``entity_map`` (user_id / ip_address / device_id / card_hash).

    Returns other cases where the entity appeared. ``recidivist_fraudster`` is true when the entity
    appears in **more than two** distinct cases other than ``exclude_case_id``.
    """
    eid = (entity_id or "").strip()[:512]
    et = _normalize_entity_type(entity_type)
    if not eid or not et:
        return {"ok": False, "error": "entity_id and valid entity_type (user_id|ip_address|device_id|card_hash) required."}

    db_acl = SessionLocal()
    try:
        tid = (tenant_id or "").strip() or (
            tenant_id_for_case(db_acl, exclude_case_id) if exclude_case_id else DEFAULT_TENANT_ID
        )
        viewer = viewer_case_id if viewer_case_id is not None else exclude_case_id
        allowed = allowed_source_case_ids(db_acl, tenant_id=tid, viewer_case_id=viewer)
    finally:
        db_acl.close()

    wh_path = Path(tenant_warehouse_path(settings.data_dir, tid))
    if not wh_path.is_file():
        return {
            "ok": True,
            "entity_id": eid,
            "entity_type": et,
            "distinct_case_count": 0,
            "other_case_count_excluding_active": 0,
            "other_cases": [],
            "recidivist_fraudster": False,
            "priority": "Normal",
            "note": "Global warehouse not initialized yet (no CSV ingested to warehouse).",
            "global_hits": False,
            "kind": "cross_case_matches",
        }

    gw = GlobalWarehouse(db_path=wh_path)
    with duckdb_lock_path(wh_path):
        con = gw._connect()
        try:
            gw.ensure_schema(con)
            cur = con.execute(
                """
                SELECT distinct_case_count, first_seen, last_seen, case_ids
                FROM entity_map
                WHERE entity_type = ? AND entity_value = ?
                LIMIT 1;
                """,
                [et, eid],
            )
            row = cur.fetchone()
            if not row:
                return {
                    "ok": True,
                    "entity_id": eid,
                    "entity_type": et,
                    "distinct_case_count": 0,
                    "other_case_count_excluding_active": 0,
                    "other_cases": [],
                    "recidivist_fraudster": False,
                    "priority": "Normal",
                    "note": "No historical rows indexed for this entity.",
                    "global_hits": False,
                    "kind": "cross_case_matches",
                }

            first_seen = row[1]
            last_seen = row[2]
            case_ids_raw = row[3]
            if case_ids_raw is None:
                case_ids: list[str] = []
            elif isinstance(case_ids_raw, list):
                case_ids = [str(x) for x in case_ids_raw]
            else:
                case_ids = [str(case_ids_raw)]

            case_ids = [c for c in case_ids if c in allowed]
            distinct_total = len(set(case_ids))

            ex = (exclude_case_id or "").strip()
            other_ids = [c for c in case_ids if c != ex]
            other_distinct = len(set(other_ids))
            recidivist = other_distinct > 2
            priority = "Recidivist Fraudster" if recidivist else ("Elevated" if other_distinct > 0 else "Normal")

            ids_for_meta = list(set(case_ids))
            if ex and ex not in ids_for_meta:
                ids_for_meta.append(ex)
            meta = _case_meta(ids_for_meta)
            other_cases: list[dict[str, Any]] = []
            for oc_id in sorted(set(other_ids), key=lambda x: (meta.get(x) or {}).get("created_at") or ""):
                m = meta.get(oc_id) or {"case_id": oc_id, "case_name": oc_id, "status": "UNKNOWN", "result_label": "Unknown"}
                other_cases.append(
                    {
                        **m,
                        "first_seen_in_warehouse": first_seen.isoformat() if hasattr(first_seen, "isoformat") else str(first_seen),
                        "last_seen_in_warehouse": last_seen.isoformat() if hasattr(last_seen, "isoformat") else str(last_seen),
                    }
                )

            out: dict[str, Any] = {
                "ok": True,
                "entity_id": eid,
                "entity_type": et,
                "distinct_case_count": distinct_total,
                "other_case_count_excluding_active": other_distinct,
                "other_cases": other_cases,
                "recidivist_fraudster": recidivist,
                "priority": priority,
                "global_hits": bool(other_distinct > 0),
                "kind": "cross_case_matches",
            }
            if other_distinct > 0:
                out["global_linkage"] = _build_global_linkage(
                    entity_id=eid,
                    entity_type=et,
                    exclude_case_id=ex,
                    other_cases=other_cases,
                    active_meta=meta.get(ex) or {},
                )
                out["global_intelligence_match"] = True
            return out
        finally:
            con.close()


def sample_entities_from_case_csv(dataset_path: str | Path, *, max_scan_rows: int = 80) -> dict[str, str]:
    """Return first seen canonical entity values from early CSV rows (for automatic overlap checks)."""
    path = Path(dataset_path)
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        df = pl.read_csv(path, n_rows=max_scan_rows, infer_schema_length=10_000, try_parse_dates=True)
    except Exception:  # noqa: BLE001
        return out
    for row in df.to_dicts():
        for et, val, _ in extract_entities_from_row(row):
            if et not in out:
                out[et] = val
        if len(out) >= 4:
            break
    return out
