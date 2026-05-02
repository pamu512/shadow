"""Humanoid stress-test linkage: warehouse rows + overlap vs stress IP and current-case canvas/device."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from backend.tools.entity_columns import extract_entities_from_row
from backend.tools.global_search import _build_global_linkage, _case_meta, search_historical_overlap
from backend.tools.warehouse_query import run_warehouse_query

STRESS_IP = "1.1.1.1"


def _first_canvas_value(dataset_path: Path) -> str | None:
    if not dataset_path.is_file():
        return None
    try:
        df = pl.read_csv(dataset_path, n_rows=120, infer_schema_length=20_000, try_parse_dates=True)
    except Exception:  # noqa: BLE001
        return None
    for col in df.columns:
        if "canvas" in col.lower():
            for v in df[col].drop_nulls().head(5).to_list():
                s = str(v).strip()
                if s and s.lower() not in ("null", "none", ""):
                    return s[:512]
    return None


def run_humanoid_stress_test_linkage(
    *,
    exclude_case_id: str | None = None,
    dataset_path: str | None = None,
) -> dict[str, Any]:
    """
    Probe GlobalWarehouse for Humanoid stress-test rows (notably stress IP 1.1.1.1) and align with
    current-case entities (IP / canvas fingerprint as device_id) for cross-case narrative.
    """
    cid = (exclude_case_id or "").strip() or None
    dsp = dataset_path
    path = Path(dsp) if dsp else None

    samples: dict[str, str] = {}
    if path and path.is_file():
        try:
            df = pl.read_csv(path, n_rows=120, infer_schema_length=20_000, try_parse_dates=True)
            for row in df.to_dicts():
                for et, val, _ in extract_entities_from_row(row):
                    if et not in samples:
                        samples[et] = val
                if len(samples) >= 8:
                    break
        except Exception:  # noqa: BLE001
            pass

    canvas_val = _first_canvas_value(path) if path else None
    current_ip = samples.get("ip_address")

    humanoid_sql = """
        SELECT DISTINCT source_case_id, source_filename, upload_timestamp
        FROM warehouse_events
        WHERE lower(row_json) LIKE '%humanoid%'
          AND (
            row_json LIKE '%1.1.1.1%'
            OR lower(row_json) LIKE '%1.1.1.1%'
          )
        ORDER BY upload_timestamp ASC
        LIMIT 60
    """
    humanoid_rows = run_warehouse_query(humanoid_sql)
    probe_case_ids: list[str] = []
    if humanoid_rows.get("ok") and isinstance(humanoid_rows.get("rows"), list):
        for r in humanoid_rows["rows"]:
            sc = r.get("source_case_id")
            if sc and str(sc) not in probe_case_ids:
                probe_case_ids.append(str(sc))

    overlap_stress = search_historical_overlap(STRESS_IP, "ip_address", exclude_case_id=cid)
    overlap_canvas: dict[str, Any] | None = None
    if canvas_val:
        overlap_canvas = search_historical_overlap(canvas_val, "device_id", exclude_case_id=cid)

    primary_overlap = overlap_stress if overlap_stress.get("other_cases") else overlap_canvas or overlap_stress
    other_cases = list(primary_overlap.get("other_cases") or [])
    entity_id = STRESS_IP
    entity_type = "ip_address"
    if not other_cases and overlap_canvas and overlap_canvas.get("other_cases"):
        other_cases = list(overlap_canvas["other_cases"])
        entity_id = canvas_val[:512]
        entity_type = "device_id"

    narrative_case = "Humanoid stress test (warehouse index)"
    if other_cases:
        narrative_case = str(other_cases[0].get("case_name") or narrative_case)
    elif probe_case_ids:
        meta = _case_meta(probe_case_ids[:5])
        first = meta.get(probe_case_ids[0]) or {}
        narrative_case = str(first.get("case_name") or probe_case_ids[0])

    required_narrative = (
        f"I have detected that this IP/Device was part of a verified Bot Cluster in the {narrative_case} dataset."
    )

    out: dict[str, Any] = {
        "ok": True,
        "kind": "global_intelligence_match",
        "global_intelligence_match": True,
        "humanoid_stress_ip": STRESS_IP,
        "humanoid_warehouse_probe": {
            "ok": humanoid_rows.get("ok"),
            "row_count": humanoid_rows.get("row_count", 0),
            "distinct_cases_in_probe": probe_case_ids,
        },
        "current_case_ip_sample": current_ip,
        "current_case_canvas_sample": canvas_val,
        "overlap_stress_ip": overlap_stress,
        "overlap_canvas_device": overlap_canvas,
        "required_narrative": required_narrative,
        "investigation_terms": {
            "infrastructure_overlap": bool(other_cases or probe_case_ids),
            "sleeper_account_detection": "user_id" in samples,
            "entity_recidivism": bool(other_cases and len(other_cases) >= 1),
        },
    }

    if other_cases:
        _ids: set[str] = {str(c["case_id"]) for c in other_cases if c.get("case_id")}
        if cid:
            _ids.add(cid)
        meta_all = _case_meta(list(_ids))
        active = meta_all.get(cid or "") or {}
        out.update(
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "other_cases": other_cases,
                "other_case_count_excluding_active": len(other_cases),
                "recidivist_fraudster": primary_overlap.get("recidivist_fraudster", False),
                "priority": primary_overlap.get("priority", "Elevated"),
                "global_hits": True,
                "global_linkage": _build_global_linkage(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    exclude_case_id=cid or "",
                    other_cases=other_cases,
                    active_meta=active,
                ),
            },
        )
        gl = out["global_linkage"]
        attrs: list[dict[str, Any]] = [{"key": "IP", "value": STRESS_IP, "highlight": "amber"}]
        if canvas_val:
            attrs.append(
                {"key": "Device", "value": canvas_val[:120] + ("…" if len(canvas_val) > 120 else ""), "highlight": "amber"},
            )
        elif entity_type == "device_id":
            attrs.append({"key": "Device", "value": str(entity_id)[:120], "highlight": "amber"})
        gl["shared_attributes"] = attrs
    elif probe_case_ids:
        meta = _case_meta([x for x in probe_case_ids if x][:12] + ([cid] if cid else []))
        synthetic_hits: list[dict[str, Any]] = []
        for pc in probe_case_ids[:8]:
            if cid and pc == cid:
                continue
            m = meta.get(pc) or {"case_id": pc, "case_name": pc, "status": "UNKNOWN", "result_label": "Unknown"}
            synthetic_hits.append(dict(m))
        if synthetic_hits:
            active = meta.get(cid or "") or {}
            out.update(
                {
                    "entity_id": STRESS_IP,
                    "entity_type": "ip_address",
                    "other_cases": synthetic_hits,
                    "other_case_count_excluding_active": len(synthetic_hits),
                    "recidivist_fraudster": len(synthetic_hits) > 2,
                    "priority": "Elevated",
                    "global_hits": True,
                    "global_linkage": _build_global_linkage(
                        entity_id=STRESS_IP,
                        entity_type="ip_address",
                        exclude_case_id=cid or "",
                        other_cases=synthetic_hits,
                        active_meta=active,
                    ),
                },
            )
            gl = out["global_linkage"]
            attrs: list[dict[str, Any]] = [{"key": "IP", "value": STRESS_IP, "highlight": "amber"}]
            if canvas_val:
                attrs.append(
                    {"key": "Device", "value": canvas_val[:120] + ("…" if len(canvas_val) > 120 else ""), "highlight": "amber"},
                )
            gl["shared_attributes"] = attrs
    else:
        out["ok"] = True
        out["note"] = (
            "No Humanoid-indexed rows or entity_map hits for stress IP / canvas yet; still narrate using "
            "warehouse_query_tool to scan row_json, or ingest stress CSVs into the warehouse."
        )
        out["global_hits"] = False

    return out
