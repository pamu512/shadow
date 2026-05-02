"""Infer session / geo / device column roles for ATO analytics over `dataset` in DuckDB."""
from __future__ import annotations

import re
from typing import Any

import duckdb

_USER_HINTS = frozenset(
    {
        "userid",
        "user_id",
        "customerid",
        "accountid",
        "accid",
        "memberid",
        "uid",
        "account_id",
        "customer_id",
        "acc_id",
    }
)
_LAT_HINTS = frozenset({"lat", "latitude", "userlat", "geo_lat", "location_lat"})
_LON_HINTS = frozenset({"lon", "lng", "longitude", "userlon", "geo_lon", "location_lon"})
_TS_HINTS = frozenset(
    {"timestamp", "eventtime", "loginat", "logints", "sessionstart", "createdat", "event_time", "login_time"}
)
_UA_HINTS = frozenset({"useragent", "user_agent", "httpuseragent", "ua", "browser"})
_SCREEN_W = frozenset({"screenwidth", "screen_w", "viewportw", "width"})
_SCREEN_H = frozenset({"screenheight", "screen_h", "viewporth", "height"})
_ISP_HINTS = frozenset({"isp", "org", "asnorg", "carrier", "network", "netname"})
_AMT_HINTS = frozenset({"amount", "txn_amount", "value", "usd", "withdrawal", "purchase_total"})
_EVENT_HINTS = frozenset({"event", "eventtype", "action", "activity", "pagename"})
_DURATION_HINTS = frozenset({"dwell", "sessionsec", "durationsec", "timespent", "navigation_ms"})
_HW_HINTS = frozenset({"deviceid", "device_id", "hardwareid", "fingerprint", "dfp"})
_OUTCOME_HINTS = frozenset(
    {
        "success",
        "loginstatus",
        "login_status",
        "outcome",
        "result",
        "status",
        "authresult",
        "eventstatus",
        "passed",
        "failed",
    }
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _pick(columns: list[str], hints: frozenset[str]) -> str | None:
    best = (0, "")
    for c in columns:
        n = _norm(c)
        score = sum(1 for h in hints if h in n)
        if score > best[0]:
            best = (score, c)
    return best[1] if best[0] > 0 else None


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def resolve_ato_columns(con: duckdb.DuckDBPyConnection, table: str = "dataset") -> dict[str, str | None]:
    rows = con.sql(f"SELECT column_name FROM (DESCRIBE {quote_ident(table)})").fetchall()
    colnames = [r[0] for r in rows]
    return {
        "user_id": _pick(colnames, _USER_HINTS),
        "latitude": _pick(colnames, _LAT_HINTS),
        "longitude": _pick(colnames, _LON_HINTS),
        "timestamp": _pick(colnames, _TS_HINTS),
        "user_agent": _pick(colnames, _UA_HINTS),
        "screen_w": _pick(colnames, _SCREEN_W),
        "screen_h": _pick(colnames, _SCREEN_H),
        "isp": _pick(colnames, _ISP_HINTS),
        "amount": _pick(colnames, _AMT_HINTS),
        "event_type": _pick(colnames, _EVENT_HINTS),
        "session_duration": _pick(colnames, _DURATION_HINTS),
        "hardware_id": _pick(colnames, _HW_HINTS),
        "outcome_status": _pick(colnames, _OUTCOME_HINTS),
    }


def fetch_column_names(con: duckdb.DuckDBPyConnection, table: str = "dataset") -> list[str]:
    rows = con.sql(f"SELECT column_name FROM (DESCRIBE {quote_ident(table)})").fetchall()
    return [r[0] for r in rows]
