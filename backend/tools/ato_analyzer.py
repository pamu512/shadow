"""Account takeover risk: compare current session telemetry to DuckDB-resident user baseline."""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from backend.database.duckdb_lock import duckdb_lock_path
from backend.database.ingestion import _configure_duckdb
from backend.tools.amount_input import normalize_mapping_amount_fields
from backend.tools.ato_columns import fetch_column_names, quote_ident, resolve_ato_columns
from backend.tools.fingerprint_velocity import analyze_canvas_ip_velocity
from backend.tools.user_profiler import build_user_behavioral_profile

_HOSTING_RE = re.compile(
    r"hosting|datacenter|data center|colo|vpn|proxy|tor|cloud\s*provider|amazon|google\s*llc|hetzner|ovh|digitalocean",
    re.I,
)


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613  # Earth radius miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    return r * c


def _parse_ts(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _session_coord(session: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = session.get("latitude", session.get("lat"))
    lon = session.get("longitude", session.get("lon", session.get("lng")))
    try:
        la = float(lat) if lat is not None else None
        lo = float(lon) if lon is not None else None
        return la, lo
    except (TypeError, ValueError):
        return None, None


def _session_ua(session: dict[str, Any]) -> str | None:
    u = session.get("user_agent") or session.get("userAgent")
    return str(u).strip() if u else None


def _session_screen(session: dict[str, Any]) -> str | None:
    w = session.get("screen_width", session.get("screenW"))
    h = session.get("screen_height", session.get("screenH"))
    try:
        if w is not None and h is not None:
            return f"{int(float(w))}x{int(float(h))}"
    except (TypeError, ValueError):
        pass
    return None


def _session_isp(session: dict[str, Any]) -> str | None:
    i = session.get("isp") or session.get("org") or session.get("asn_org")
    return str(i).strip() if i else None


def _notification_trusted_email(session: dict[str, Any]) -> str | None:
    """Email that predates attacker changes — notify here, not the in-session primary if it was just changed."""
    for key in (
        "original_email",
        "pre_change_email",
        "email_on_file",
        "registered_email",
        "trusted_contact_email",
        "email_before_change",
    ):
        v = session.get(key)
        if v and str(v).strip():
            return str(v).strip()
    events = session.get("events") or []
    if isinstance(events, list):
        for e in events:
            if not isinstance(e, dict):
                continue
            et = str(e.get("type") or e.get("event") or "").lower().replace(" ", "_")
            if "email" in et and any(x in et for x in ("change", "update", "edit")):
                old = e.get("previous_email") or e.get("old_email") or e.get("from") or e.get("prior_email")
                if old and str(old).strip():
                    return str(old).strip()
    return None


def _last_login_lat_lon_time(
    con: duckdb.DuckDBPyConnection,
    table: str,
    cols: dict[str, str | None],
    user_col: str,
    uid: str,
) -> tuple[float | None, float | None, datetime | None]:
    tq, uq = quote_ident(table), quote_ident(user_col)
    lat_c, lon_c, ts_c = cols.get("latitude"), cols.get("longitude"), cols.get("timestamp")
    if not (lat_c and lon_c and ts_c):
        return None, None, None
    la, lo, tsc = quote_ident(lat_c), quote_ident(lon_c), quote_ident(ts_c)
    row = con.sql(
        f"""
        SELECT TRY_CAST({la} AS DOUBLE), TRY_CAST({lo} AS DOUBLE),
               TRY_CAST({tsc} AS TIMESTAMP)
        FROM {tq}
        WHERE CAST({uq} AS VARCHAR) = ?
          AND TRY_CAST({la} AS DOUBLE) IS NOT NULL
          AND TRY_CAST({lo} AS DOUBLE) IS NOT NULL
          AND TRY_CAST({tsc} AS TIMESTAMP) IS NOT NULL
        ORDER BY TRY_CAST({tsc} AS TIMESTAMP) DESC
        LIMIT 1
        """,
        params=[uid],
    ).fetchone()
    if not row:
        return None, None, None
    lat, lon, t = row[0], row[1], row[2]
    if lat is None or lon is None:
        return None, None, None
    dt = t if isinstance(t, datetime) else _parse_ts(t)
    return float(lat), float(lon), dt


def infer_user_id_from_duckdb(
    duckdb_path: str | Path,
    *,
    user_column: str | None = None,
    table: str = "dataset",
) -> tuple[str | None, str | None, dict[str, Any]]:
    """
    Resolve the account-id column from schema (user_id, acc_id, …) and pick the most frequent non-null value
    as a self-healing default when the operator omits user_id.
    """
    path = Path(duckdb_path)
    if not path.is_file():
        return None, None, {"error": f"DuckDB not found: {path}"}
    with duckdb_lock_path(path):
        con = duckdb.connect(str(path), read_only=True)
        try:
            try:
                _configure_duckdb(con)
            except Exception:  # noqa: BLE001
                pass
            cols = resolve_ato_columns(con, table)
            uc = (user_column or "").strip() or cols.get("user_id")
            names = fetch_column_names(con, table)
            if not uc or uc not in names:
                return None, None, {
                    "error": "Could not resolve a user / account id column (looked for user_id, acc_id, customer_id, …).",
                    "columns": names,
                }
            uq, tq = quote_ident(uc), quote_ident(table)
            row = con.sql(
                f"""
                SELECT CAST({uq} AS VARCHAR) AS uid, COUNT(*) AS n
                FROM {tq}
                WHERE {uq} IS NOT NULL AND TRIM(CAST({uq} AS VARCHAR)) <> ''
                GROUP BY 1
                ORDER BY n DESC
                LIMIT 1
                """,
            ).fetchone()
            if not row or not row[0]:
                return None, uc, {
                    "error": "Dataset has no non-null user identifiers in the resolved column.",
                    "column": uc,
                }
            return str(row[0]).strip(), uc, {"inferred_rank_count": int(row[1])}
        finally:
            con.close()


_FLAG_PUBLIC_LABELS: dict[str, str] = {
    "IMPOSSIBLE_TRAVEL": "Geographic anomaly: impossible travel",
    "USER_AGENT_MISMATCH": "Device signature: first-time login on this hardware (user agent)",
    "SCREEN_ENV_MISMATCH": "Device signature: unfamiliar screen resolution",
    "HOSTING_OR_PROXY_ISP": "Network type: data center / VPN pattern detected",
    "ISP_MISMATCH": "Network ISP differs from typical residential history",
    "NEW_HARDWARE_ID": "Device signature: first-time hardware id for this account",
    "SENSITIVE_CHAIN_HIGH_VALUE": "Account change followed by high-value movement",
    "NAVIGATION_SPEED_ANOMALY": "Session timing: unusually fast navigation vs baseline",
}


def _public_label_for_flag(code: str) -> str:
    return _FLAG_PUBLIC_LABELS.get(code, code.replace("_", " ").title())


def analyze_ato_risk(
    duckdb_path: str | Path,
    user_id: str,
    current_session_data: dict[str, Any],
    *,
    user_column: str | None = None,
    impossible_travel_mph_threshold: float = 500.0,
    table: str = "dataset",
) -> dict[str, Any]:
    """
    Compare ``current_session_data`` to historical rows for ``user_id`` in the case DuckDB.

    Detection focus: impossible travel (geo velocity), environmental mismatch vs top-N baseline,
    sensitive action → high-value transfer chains, navigation speed vs typical dwell/checkout times.
    """
    path = Path(duckdb_path)
    if not path.is_file():
        return {"ok": False, "error": f"DuckDB not found: {path}"}

    if not isinstance(current_session_data, dict):
        return {"ok": False, "error": "current_session_data must be an object."}

    current_session_data = normalize_mapping_amount_fields(dict(current_session_data))

    uid = str(user_id).strip()
    user_id_source: str = "explicit"
    inferred_user_column: str | None = None
    if not uid:
        inferred_uid, inferred_uc, meta = infer_user_id_from_duckdb(
            path,
            user_column=user_column,
            table=table,
        )
        if not inferred_uid:
            return {
                "ok": False,
                "error": meta.get("error", "user_id required (or ingest a CSV with acc_id / user_id)."),
                **{k: v for k, v in meta.items() if k != "error"},
            }
        uid = inferred_uid
        inferred_user_column = inferred_uc
        user_id_source = "schema_inferred"

    effective_user_column = user_column or inferred_user_column
    profile = build_user_behavioral_profile(path, uid, user_column=effective_user_column, table=table)
    if not profile.get("ok"):
        return profile

    dna = profile.get("behavioral_dna") or {}
    cur_lat, cur_lon = _session_coord(current_session_data)
    cur_ts = _parse_ts(current_session_data.get("timestamp") or current_session_data.get("session_start"))
    cur_ua = _session_ua(current_session_data)
    cur_screen = _session_screen(current_session_data)
    cur_isp = _session_isp(current_session_data)
    cur_hw = current_session_data.get("hardware_id") or current_session_data.get("device_id")

    flags: list[dict[str, Any]] = []
    discrepancies: list[dict[str, Any]] = []
    travel_map: dict[str, Any] | None = None

    with duckdb_lock_path(path):
        con = duckdb.connect(str(path), read_only=True)
        try:
            try:
                _configure_duckdb(con)
            except Exception:  # noqa: BLE001
                pass
            cols = resolve_ato_columns(con, table)
            uc = effective_user_column or cols.get("user_id")
            if not uc or uc not in fetch_column_names(con, table):
                return {"ok": False, "error": "User column unresolved.", "profile": profile}

            last_lat, last_lon, last_ts = _last_login_lat_lon_time(con, table, cols, uc, uid)

            if (
                cur_lat is not None
                and cur_lon is not None
                and last_lat is not None
                and last_lon is not None
                and cur_ts
                and last_ts
            ):
                dist = _haversine_miles(last_lat, last_lon, cur_lat, cur_lon)
                dt_h = abs((cur_ts - last_ts).total_seconds()) / 3600.0
                if dt_h > 1e-6:
                    mph = dist / dt_h
                    if mph > impossible_travel_mph_threshold:
                        flags.append(
                            {
                                "code": "IMPOSSIBLE_TRAVEL",
                                "severity": "critical",
                                "public_label": _public_label_for_flag("IMPOSSIBLE_TRAVEL"),
                                "detail": (
                                    f"~{dist:.0f} mi in {dt_h * 60:.1f} min implies ~{mph:.0f} mph "
                                    f"(threshold {impossible_travel_mph_threshold:.0f} mph). "
                                    f"Prior point ({last_lat:.4f},{last_lon:.4f}) vs current ({cur_lat:.4f},{cur_lon:.4f})."
                                ),
                            }
                        )
                        discrepancies.append(
                            {
                                "field": "geo_velocity",
                                "public_label": "Geographic anomaly: impossible travel",
                                "baseline_label": "last_known_login",
                                "baseline_value": f"{last_lat:.4f},{last_lon:.4f} @ {last_ts.isoformat()}",
                                "current_value": f"{cur_lat:.4f},{cur_lon:.4f} @ {cur_ts.isoformat()}",
                                "severity": "critical",
                            }
                        )
                        travel_map = {
                            "prior": {"lat": last_lat, "lon": last_lon, "label": "Last known session"},
                            "current": {"lat": cur_lat, "lon": cur_lon, "label": "This login"},
                            "distance_miles": round(dist, 1),
                            "elapsed_hours": round(dt_h, 4),
                            "implied_mph": round(mph, 0),
                        }

            top_uas = [x.get("user_agent") for x in dna.get("common_user_agents") or []][:3]
            if cur_ua and top_uas:
                if not any(cur_ua == u or cur_ua in str(u) for u in top_uas if u):
                    flags.append(
                        {
                            "code": "USER_AGENT_MISMATCH",
                            "severity": "high",
                            "detail": f"Current UA not in user's top {len(top_uas)} historical UAs.",
                        }
                    )
                    discrepancies.append(
                        {
                            "field": "user_agent",
                            "baseline_label": "top_historical_uas",
                            "baseline_value": "; ".join(str(u) for u in top_uas if u),
                            "current_value": cur_ua[:512],
                            "severity": "high",
                        }
                    )

            top_screens = [x.get("resolution") for x in dna.get("common_screen_resolutions") or []][:3]
            if cur_screen and top_screens:
                if cur_screen not in top_screens:
                    flags.append(
                        {
                            "code": "SCREEN_ENV_MISMATCH",
                            "severity": "medium",
                            "detail": "Screen resolution outside top historical configurations.",
                        }
                    )
                    discrepancies.append(
                        {
                            "field": "screen_resolution",
                            "baseline_label": "top_resolutions",
                            "baseline_value": ", ".join(str(s) for s in top_screens if s),
                            "current_value": cur_screen,
                            "severity": "medium",
                        }
                    )

            top_isps = [x.get("isp") for x in dna.get("typical_isps") or []][:3]
            if cur_isp:
                hosting = bool(current_session_data.get("is_hosting_or_proxy")) or bool(
                    _HOSTING_RE.search(cur_isp)
                )
                if hosting:
                    flags.append(
                        {
                            "code": "HOSTING_OR_PROXY_ISP",
                            "severity": "high",
                            "detail": f"Session ISP/org suggests hosting/VPN/datacenter pattern: {cur_isp!r}.",
                        }
                    )
                    discrepancies.append(
                        {
                            "field": "isp_reputation",
                            "baseline_label": "typical_residential_isps",
                            "baseline_value": ", ".join(str(i) for i in top_isps if i) or "(none inferred)",
                            "current_value": cur_isp,
                            "severity": "high",
                        }
                    )
                elif top_isps and not any(
                    str(t).lower() in cur_isp.lower() or cur_isp.lower() in str(t).lower() for t in top_isps if t
                ):
                    flags.append(
                        {
                            "code": "ISP_MISMATCH",
                            "severity": "medium",
                            "detail": "ISP/org diverges from typical user networks.",
                        }
                    )
                    discrepancies.append(
                        {
                            "field": "isp",
                            "baseline_label": "top_isps",
                            "baseline_value": ", ".join(str(i) for i in top_isps if i),
                            "current_value": cur_isp,
                            "severity": "medium",
                        }
                    )

            trusted_hw = [x.get("hardware_id") for x in dna.get("trusted_devices_hardware_ids") or []]
            if cur_hw and trusted_hw:
                ch = str(cur_hw)
                if not any(ch == str(h) for h in trusted_hw if h):
                    flags.append(
                        {
                            "code": "NEW_HARDWARE_ID",
                            "severity": "low",
                            "detail": "First-seen hardware/device id for this account in dataset — elevate with other red flags.",
                        }
                    )
                    discrepancies.append(
                        {
                            "field": "hardware_id",
                            "baseline_label": "known_device_ids",
                            "baseline_value": ", ".join(str(h) for h in trusted_hw[:5] if h),
                            "current_value": ch[:256],
                            "severity": "low",
                        }
                    )

        finally:
            con.close()

    # --- Sensitive action chain (session payload; not always in CSV) ---
    events = current_session_data.get("events") or []
    sensitive_types = {"password_change", "email_change", "email_update", "mfa_reset", "mfa_disable", "phone_change"}
    had_sensitive = False
    if isinstance(events, list):
        for e in events:
            if not isinstance(e, dict):
                continue
            et = str(e.get("type") or e.get("event") or "").lower().replace(" ", "_")
            if any(s in et for s in sensitive_types):
                had_sensitive = True
                break
    elif current_session_data.get("password_changed") or current_session_data.get("email_changed"):
        had_sensitive = True

    hv = current_session_data.get("high_value_amount") or current_session_data.get("transfer_amount")
    try:
        hv_f = float(hv) if hv is not None else None
    except (TypeError, ValueError):
        hv_f = None
    avg_amt = None
    ta = dna.get("transaction_amount_stats") or {}
    if isinstance(ta, dict) and ta.get("avg") is not None:
        avg_amt = float(ta["avg"])

    if had_sensitive and hv_f and avg_amt and hv_f >= max(500.0, avg_amt * 3):
        flags.append(
            {
                "code": "SENSITIVE_CHAIN_HIGH_VALUE",
                "severity": "critical",
                "detail": f"Credential or MFA lifecycle change proximate to high-value movement (${hv_f:.2f} vs avg ${avg_amt:.2f}).",
            }
        )
        discrepancies.append(
            {
                "field": "account_change_chain",
                "baseline_label": "typical_avg_amount",
                "baseline_value": f"avg ${avg_amt:.2f}",
                "current_value": f"sensitive events + ${hv_f:.2f}",
                "severity": "critical",
            }
        )

    # --- Navigation / speed-running ---
    checkout_sec = current_session_data.get("checkout_duration_seconds")
    try:
        csec = float(checkout_sec) if checkout_sec is not None else None
    except (TypeError, ValueError):
        csec = None
    dur_dna = dna.get("typical_session_duration_seconds") or {}
    median_dur = dur_dna.get("median") or dur_dna.get("mean")
    if csec is not None and median_dur and float(median_dur) > 30 and csec < float(median_dur) * 0.15:
        flags.append(
            {
                "code": "NAVIGATION_SPEED_ANOMALY",
                "severity": "medium",
                "detail": (
                    f"Checkout path completed in {csec:.1f}s vs typical engagement ~{float(median_dur):.1f}s "
                    "(possible speed-running)."
                ),
            }
        )
        discrepancies.append(
            {
                "field": "checkout_duration_seconds",
                "baseline_label": "typical_session_seconds",
                "baseline_value": str(median_dur),
                "current_value": str(csec),
                "severity": "medium",
            }
        )

    _disc_public_labels: dict[str, str] = {
        "user_agent": "Device signature: first-time login on this hardware (user agent)",
        "screen_resolution": "Device signature: unfamiliar screen resolution",
        "isp_reputation": "Network type: data center / VPN pattern detected",
        "isp": "Network ISP differs from typical residential history",
        "hardware_id": "Device signature: first-time hardware id for this account",
        "account_change_chain": "Sensitive account change near high-value movement",
        "checkout_duration_seconds": "Session timing: unusually fast vs baseline",
    }
    for f in flags:
        if "public_label" not in f:
            f["public_label"] = _public_label_for_flag(str(f.get("code") or ""))
    for d in discrepancies:
        if not d.get("public_label"):
            fld = str(d.get("field") or "")
            d["public_label"] = _disc_public_labels.get(fld, fld.replace("_", " ").title() if fld else "Signal")

    sev_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    risk = min(
        100.0,
        sum(sev_rank.get(f.get("severity", "low"), 1) * 12 for f in flags) + len(flags) * 3,
    )
    safety = max(0.0, min(100.0, round(100.0 - risk, 1)))
    notify_email = _notification_trusted_email(current_session_data)

    if any(f.get("code") == "IMPOSSIBLE_TRAVEL" for f in flags):
        fv_headline = "Physically impossible travel vs prior session"
    elif risk >= 60:
        fv_headline = "Elevated account takeover risk"
    elif risk >= 35:
        fv_headline = "Moderate environment drift vs baseline"
    else:
        fv_headline = "Limited automated ATO signals"

    forensic_verdict = {
        "kind": "ato_forensic_verdict",
        "headline": fv_headline,
        "risk_gauge_0_100": round(risk, 1),
        "safety_gauge_0_100": safety,
        "bullets": [str(f.get("public_label") or _public_label_for_flag(str(f.get("code") or ""))) for f in flags],
    }

    narrative_hints = [
        "Credentials may be valid while **environment** diverges from baseline (ISP/UA/geo).",
        "Prioritize **freezing high-risk rails** when sensitive changes precede cash-out sized moves.",
    ]

    canvas_ip: dict[str, Any] | None = None
    try:
        canvas_ip = analyze_canvas_ip_velocity(path, table=table)
    except Exception:
        canvas_ip = {"ok": False, "error": "canvas_ip_velocity_failed"}
    if any(f["code"] == "IMPOSSIBLE_TRAVEL" for f in flags):
        narrative_hints.append(
            "Cite **impossible travel** with prior vs current coordinates and elapsed time for SOC escalation."
        )

    return {
        "ok": True,
        "user_id": uid,
        "user_id_source": user_id_source,
        "travel_map": travel_map,
        "forensic_verdict": forensic_verdict,
        "historical_baseline": {
            "behavioral_dna": dna,
            "historical_event_count": profile.get("historical_event_count"),
            "columns_used": profile.get("columns_used"),
        },
        "current_session": {
            "latitude": cur_lat,
            "longitude": cur_lon,
            "timestamp": cur_ts.isoformat() if cur_ts else None,
            "user_agent": cur_ua,
            "screen_resolution": cur_screen,
            "isp": cur_isp,
            "hardware_id": str(cur_hw) if cur_hw else None,
            "raw": current_session_data,
        },
        "flags": flags,
        "discrepancies": discrepancies,
        "ato_risk_score": round(risk, 1),
        "safety_score": safety,
        "notification_recipient_email": notify_email,
        "narrative_hints": narrative_hints,
        "thresholds": {"impossible_travel_mph": impossible_travel_mph_threshold},
        "canvas_ip_velocity": canvas_ip,
    }
