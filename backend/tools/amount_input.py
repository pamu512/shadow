"""Normalize money-like values from tool/API inputs (currency symbols, grouping commas)."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_CURRENCY_AND_SPACE = re.compile(r"[\$€£¥₹₽¢\s\u00a0\u202f]")


def parse_loose_amount(value: Any) -> float | None:
    """Strip common currency symbols and commas, then parse to float. Returns None if not parseable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
    s = _CURRENCY_AND_SPACE.sub("", s)
    s = s.replace(",", "")
    if not s or s in (".", "-", "-."):
        return None
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        try:
            v = float(Decimal(s))
            return -v if neg else v
        except (InvalidOperation, ValueError):
            return None


_AMOUNT_LIKE_KEYS = frozenset(
    {
        "high_value_amount",
        "transfer_amount",
        "amount",
        "txn_amount",
        "payment_amount",
        "purchase_total",
        "balance",
        "withdrawal_amount",
        "order_total",
        "cart_total",
        "refund_amount",
    },
)


def normalize_mapping_amount_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Shallow copy: coerce known money-like string keys to floats where parseable."""
    out = dict(data)
    for k in _AMOUNT_LIKE_KEYS:
        if k not in out:
            continue
        parsed = parse_loose_amount(out[k])
        if parsed is not None:
            out[k] = parsed
    return out
