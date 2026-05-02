"""Build a 'Behavioral DNA' baseline per user from historical session rows in DuckDB."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from backend.database.ingestion import _configure_duckdb
from backend.tools.ato_columns import fetch_column_names, quote_ident, resolve_ato_columns


def build_user_behavioral_profile(
    duckdb_path: str | Path,
    user_id: str,
    *,
    user_column: str | None = None,
    table: str = "dataset",
) -> dict[str, Any]:
    """
    Summarize login-time preferences, common devices, typical locations, and spend for one user.

    Requires a case DuckDB file (table ``dataset``) with inferable column roles.
    """
    path = Path(duckdb_path)
    if not path.is_file():
        return {"ok": False, "error": f"DuckDB file not found: {path}"}

    uid = str(user_id).strip()
    if not uid:
        return {"ok": False, "error": "user_id is required."}

    con = duckdb.connect(str(path), read_only=True)
    try:
        try:
            _configure_duckdb(con)
        except Exception:  # noqa: BLE001
            pass
        cols = resolve_ato_columns(con, table)
        uc = user_column or cols.get("user_id")
        if not uc or uc not in fetch_column_names(con, table):
            return {
                "ok": False,
                "error": "Could not resolve user id column; pass user_column explicitly.",
                "available_columns": fetch_column_names(con, table),
            }

        uq = quote_ident(uc)
        tq = quote_ident(table)

        profile: dict[str, Any] = {
            "ok": True,
            "user_id": uid,
            "columns_used": {k: v for k, v in cols.items() if v},
            "user_column": uc,
        }

        n_rows = con.sql(f"SELECT COUNT(*) FROM {tq} WHERE CAST({uq} AS VARCHAR) = ?", params=[uid]).fetchone()[0]
        profile["historical_event_count"] = int(n_rows)

        if n_rows == 0:
            profile["behavioral_dna"] = {}
            profile["note"] = "No historical rows for this user in dataset."
            return profile

        dna: dict[str, Any] = {}

        ts_col = cols.get("timestamp")
        if ts_col:
            tsc = quote_ident(ts_col)
            hour_hist = con.sql(
                f"""
                SELECT EXTRACT(HOUR FROM CAST({tsc} AS TIMESTAMP)) AS hr, COUNT(*) AS c
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ?
                  AND TRY_CAST({tsc} AS TIMESTAMP) IS NOT NULL
                GROUP BY 1 ORDER BY c DESC LIMIT 5
                """,
                params=[uid],
            ).fetchall()
            dna["preferred_login_hours_utc"] = [{"hour": int(h), "count": int(c)} for h, c in hour_hist if h is not None]

        ua_col = cols.get("user_agent")
        if ua_col:
            uac = quote_ident(ua_col)
            top_ua = con.sql(
                f"""
                SELECT CAST({uac} AS VARCHAR) AS ua, COUNT(*) AS c
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ? AND {uac} IS NOT NULL
                GROUP BY 1 ORDER BY c DESC LIMIT 5
                """,
                params=[uid],
            ).fetchall()
            dna["common_user_agents"] = [{"user_agent": str(u), "count": int(c)} for u, c in top_ua]

        sw, sh = cols.get("screen_w"), cols.get("screen_h")
        if sw and sh and sw in fetch_column_names(con, table) and sh in fetch_column_names(con, table):
            swq, shq = quote_ident(sw), quote_ident(sh)
            screens = con.sql(
                f"""
                SELECT CAST({swq} AS VARCHAR) || 'x' || CAST({shq} AS VARCHAR) AS res, COUNT(*) AS c
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ?
                GROUP BY 1 ORDER BY c DESC LIMIT 5
                """,
                params=[uid],
            ).fetchall()
            dna["common_screen_resolutions"] = [{"resolution": str(r), "count": int(c)} for r, c in screens]

        isp_col = cols.get("isp")
        if isp_col:
            ispc = quote_ident(isp_col)
            top_isp = con.sql(
                f"""
                SELECT CAST({ispc} AS VARCHAR) AS isp, COUNT(*) AS c
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ? AND {ispc} IS NOT NULL
                GROUP BY 1 ORDER BY c DESC LIMIT 5
                """,
                params=[uid],
            ).fetchall()
            dna["typical_isps"] = [{"isp": str(i), "count": int(c)} for i, c in top_isp]

        lat_c, lon_c = cols.get("latitude"), cols.get("longitude")
        if lat_c and lon_c:
            la, lo = quote_ident(lat_c), quote_ident(lon_c)
            locs = con.sql(
                f"""
                SELECT ROUND(CAST({la} AS DOUBLE), 3) AS lat,
                       ROUND(CAST({lo} AS DOUBLE), 3) AS lon,
                       COUNT(*) AS c
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ?
                  AND TRY_CAST({la} AS DOUBLE) IS NOT NULL
                  AND TRY_CAST({lo} AS DOUBLE) IS NOT NULL
                GROUP BY 1, 2 ORDER BY c DESC LIMIT 5
                """,
                params=[uid],
            ).fetchall()
            dna["typical_login_locations"] = [
                {"lat": float(lat), "lon": float(lon), "count": int(c)} for lat, lon, c in locs
            ]

        amt_col = cols.get("amount")
        if amt_col:
            am = quote_ident(amt_col)
            agg = con.sql(
                f"""
                SELECT AVG(TRY_CAST({am} AS DOUBLE)), MAX(TRY_CAST({am} AS DOUBLE)), COUNT(*)
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ?
                """,
                params=[uid],
            ).fetchone()
            if agg[0] is not None:
                dna["transaction_amount_stats"] = {
                    "avg": round(float(agg[0]), 4),
                    "max": round(float(agg[1]), 4) if agg[1] is not None else None,
                    "samples": int(agg[2]),
                }

        hw = cols.get("hardware_id")
        if hw:
            hwq = quote_ident(hw)
            devc = con.sql(
                f"""
                SELECT CAST({hwq} AS VARCHAR) AS d, COUNT(*) AS c
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ? AND {hwq} IS NOT NULL
                GROUP BY 1 ORDER BY c DESC LIMIT 5
                """,
                params=[uid],
            ).fetchall()
            dna["trusted_devices_hardware_ids"] = [{"hardware_id": str(d), "count": int(c)} for d, c in devc]

        dur_col = cols.get("session_duration")
        if dur_col:
            dq = quote_ident(dur_col)
            dstats = con.sql(
                f"""
                SELECT AVG(TRY_CAST({dq} AS DOUBLE)),
                       quantile_cont(TRY_CAST({dq} AS DOUBLE), 0.5)
                FROM {tq}
                WHERE CAST({uq} AS VARCHAR) = ?
                  AND TRY_CAST({dq} AS DOUBLE) IS NOT NULL
                """,
                params=[uid],
            ).fetchone()
            if dstats[0] is not None:
                dna["typical_session_duration_seconds"] = {
                    "mean": round(float(dstats[0]), 2),
                    "median": round(float(dstats[1]), 2) if dstats[1] is not None else None,
                }

        profile["behavioral_dna"] = dna
        return profile
    finally:
        con.close()


def fetch_last_successful_login_sessions(
    duckdb_path: str | Path,
    user_id: str,
    *,
    user_column: str | None = None,
    limit: int = 10,
    table: str = "dataset",
) -> dict[str, Any]:
    """
    Pull the last N login/session rows for a user, preferring rows marked successful when an
    outcome/status column exists; otherwise orders by timestamp descending.
    """
    path = Path(duckdb_path)
    if not path.is_file():
        return {"ok": False, "error": f"DuckDB file not found: {path}"}
    uid = str(user_id).strip()
    if not uid:
        return {"ok": False, "error": "user_id is required."}
    lim = max(1, min(50, int(limit)))

    con = duckdb.connect(str(path), read_only=True)
    try:
        try:
            _configure_duckdb(con)
        except Exception:  # noqa: BLE001
            pass
        cols = resolve_ato_columns(con, table)
        uc = user_column or cols.get("user_id")
        if not uc or uc not in fetch_column_names(con, table):
            return {
                "ok": False,
                "error": "Could not resolve user id column; pass user_column explicitly.",
                "available_columns": fetch_column_names(con, table),
            }
        uq = quote_ident(uc)
        tq = quote_ident(table)
        ts_col = cols.get("timestamp")
        out_col = cols.get("outcome_status")

        success_filter = ""
        if out_col and out_col in fetch_column_names(con, table):
            oq = quote_ident(out_col)
            success_filter = f""" AND (
                LOWER(CAST({oq} AS VARCHAR)) IN (
                    'success', 'true', '1', 'ok', 'passed', 'succeeded', 'successful', 'completed'
                )
                OR TRY_CAST({oq} AS BOOLEAN) = true
            )"""

        if ts_col and ts_col in fetch_column_names(con, table):
            tsc = quote_ident(ts_col)
            order_sql = f"ORDER BY TRY_CAST({tsc} AS TIMESTAMP) DESC NULLS LAST"
        else:
            order_sql = ""

        sql = f"""
            SELECT * FROM {tq}
            WHERE CAST({uq} AS VARCHAR) = ?{success_filter}
            {order_sql}
            LIMIT {lim}
        """
        rel = con.sql(sql, params=[uid])
        colnames = list(rel.columns)
        rows = rel.fetchall()
        sessions = [dict(zip(colnames, r, strict=False)) for r in rows]

        return {
            "ok": True,
            "user_id": uid,
            "user_column": uc,
            "columns_used": {k: v for k, v in cols.items() if v},
            "outcome_column_used": bool(out_col and out_col in fetch_column_names(con, table)),
            "session_count": len(sessions),
            "sessions": sessions,
            "note": (
                "Successful-login filter applied to outcome column."
                if out_col and success_filter
                else "No outcome column inferred; returning last rows by time (or arbitrary order)."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()
