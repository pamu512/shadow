"""Map CSV column names to canonical entity types for the global warehouse ledger."""
from __future__ import annotations

import re
from typing import Final

_USER_HINTS: Final[frozenset[str]] = frozenset(
    {
        "userid",
        "user_id",
        "customerid",
        "customer_id",
        "accountid",
        "account_id",
        "memberid",
        "buyerid",
        "payerid",
    },
)
_IP_HINTS: Final[frozenset[str]] = frozenset(
    {
        "ip",
        "ipaddress",
        "ip_address",
        "clientip",
        "client_ip",
        "remoteip",
        "signupip",
        "registrationip",
        "sourceip",
    },
)
_DEVICE_HINTS: Final[frozenset[str]] = frozenset(
    {
        "deviceid",
        "device_id",
        "devicefingerprint",
        "fingerprint",
        "hardwareid",
        "hardware_id",
        "dfp",
        "browserfingerprint",
        "canvasfingerprint",
        "canvas_fingerprint",
        "canvasfp",
    },
)
_CARD_HINTS: Final[frozenset[str]] = frozenset(
    {
        "cardhash",
        "card_hash",
        "panhash",
        "pan_hash",
        "paymenttoken",
        "payment_token",
        "instrumenthash",
        "cardfingerprint",
        "tokenhash",
    },
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def entity_type_for_column(column_name: str) -> str | None:
    """Return canonical entity_type or None if column is not indexed."""
    n = _norm(column_name)
    if any(h in n for h in _USER_HINTS):
        return "user_id"
    if any(h in n for h in _IP_HINTS):
        return "ip_address"
    if any(h in n for h in _DEVICE_HINTS):
        return "device_id"
    if any(h in n for h in _CARD_HINTS):
        return "card_hash"
    return None


def extract_entities_from_row(row: dict[str, object]) -> list[tuple[str, str, str]]:
    """
    From one CSV row dict, return list of (entity_type, entity_value, source_column_name).
    Values are trimmed and truncated; empty values skipped.
    """
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for col, raw in row.items():
        et = entity_type_for_column(str(col))
        if not et:
            continue
        if raw is None:
            continue
        val = str(raw).strip()
        if not val or val.lower() in ("null", "none", "nan"):
            continue
        val = val[:512]
        key = (et, val)
        if key in seen:
            continue
        seen.add(key)
        out.append((et, val, str(col)))
    return out
