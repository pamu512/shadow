"""DuckDB: canvas / hardware fingerprint concentration + IP velocity (windowed events per hour)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb

from backend.database.duckdb_lock import duckdb_lock_path
from backend.database.ingestion import _configure_duckdb
from backend.tools.ato_columns import quote_ident


def _norm(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(n).lower())


def _pick_canvas_ip(names: list[str]) -> tuple[str | None, str | None]:
    canvas = None
    ip_col = None
    for c in names:
        n = _norm(c)
        if canvas is None and ("canvas" in n or "fingerprint" in n or "deviceprint" in n):
            canvas = c
        if ip_col is None and (n == "ip" or "ipaddress" in n or "clientip" in n or n.endswith("ipaddr")):
            ip_col = c
    return canvas, ip_col


def analyze_canvas_ip_velocity(duckdb_path: str | Path, *, table: str = "dataset") -> dict[str, Any]:
    """SQL window: events per account per hour + dominant canvas share (bot-farm signal)."""
    path = Path(duckdb_path)
    if not path.is_file():
        return {"ok": False, "error": f"DuckDB not found: {path}"}
    with duckdb_lock_path(path):
        con = duckdb.connect(str(path), read_only=True)
        try:
            try:
                _configure_duckdb(con)
            except Exception:
                pass
            rows = con.sql(f"SELECT column_name FROM (DESCRIBE {quote_ident(table)})").fetchall()
            names = [r[0] for r in rows]
            canvas_c, ip_c = _pick_canvas_ip(names)
            tq = quote_ident(table)
            out: dict[str, Any] = {"ok": True, "table": table, "canvas_column": canvas_c, "ip_column": ip_c}
            if canvas_c and ip_c:
                cq, iq = quote_ident(canvas_c), quote_ident(ip_c)
                share = con.sql(
                    f"""
                    WITH base AS (
                      SELECT TRIM(CAST({cq} AS VARCHAR)) AS cf, TRIM(CAST({iq} AS VARCHAR)) AS ip
                      FROM {tq}
                      WHERE {cq} IS NOT NULL AND TRIM(CAST({cq} AS VARCHAR)) <> ''
                        AND {iq} IS NOT NULL AND TRIM(CAST({iq} AS VARCHAR)) <> ''
                    ),
                    agg AS (
                      SELECT cf, COUNT(*) AS n, COUNT(DISTINCT ip) AS distinct_ips
                      FROM base
                      GROUP BY 1
                    )
                    SELECT cf, n, distinct_ips, ROUND(100.0 * n / SUM(n) OVER (), 2) AS pct_of_rows
                    FROM agg
                    ORDER BY n DESC
                    LIMIT 12
                    """
                ).fetchall()
                out["dominant_canvas_fingerprints"] = [
                    {"canvas_fingerprint": r[0], "rows": int(r[1]), "distinct_ips": int(r[2]), "pct_of_rows": float(r[3])}
                    for r in share
                ]
            ts_c = None
            uid_c = None
            for c in names:
                n = _norm(c)
                if ts_c is None and any(x in n for x in ("timestamp", "eventtime", "createdat", "logints")):
                    ts_c = c
                if uid_c is None and any(
                    x in n for x in ("userid", "user_id", "accid", "accountid", "customerid", "uid")
                ):
                    uid_c = c
            if ts_c and uid_c and ip_c:
                tsc, uc, ipc = quote_ident(ts_c), quote_ident(uid_c), quote_ident(ip_c)
                vel = con.sql(
                    f"""
                    WITH ev AS (
                      SELECT
                        TRIM(CAST({uc} AS VARCHAR)) AS uid,
                        TRIM(CAST({ipc} AS VARCHAR)) AS ip,
                        TRY_CAST({tsc} AS TIMESTAMP) AS ts
                      FROM {tq}
                      WHERE {uc} IS NOT NULL AND {ipc} IS NOT NULL AND TRY_CAST({tsc} AS TIMESTAMP) IS NOT NULL
                    ),
                    w AS (
                      SELECT uid, ip, ts,
                        COUNT(*) OVER (
                          PARTITION BY uid, ip
                          ORDER BY ts
                          RANGE BETWEEN INTERVAL 1 HOUR PRECEDING AND CURRENT ROW
                        ) AS events_per_hour_window
                      FROM ev
                    )
                    SELECT uid, ip, MAX(events_per_hour_window) AS peak_events_1h
                    FROM w
                    GROUP BY 1, 2
                    HAVING MAX(events_per_hour_window) >= 8
                    ORDER BY peak_events_1h DESC
                    LIMIT 20
                    """
                ).fetchall()
                out["high_ip_velocity_pairs"] = [
                    {"user_id": r[0], "ip": r[1], "peak_events_1h": int(r[2])} for r in vel
                ]
            else:
                out["high_ip_velocity_pairs"] = []
                if not (ts_c and uid_c and ip_c):
                    out["velocity_note"] = "Need timestamp + user + IP columns for 1h velocity window."
            return out
        finally:
            con.close()
