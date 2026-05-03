"""Proactive Trust vs. Velocity scan for chargeback / friendly-fraud triage (single CSV pass)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import polars as pl

from backend.tools.amount_input import parse_loose_amount

_USER_HINTS = frozenset(
    {"userid", "user_id", "customerid", "account", "accountid", "buyerid"},
)
_TXN_HINTS = frozenset(
    {"transaction", "transactionid", "orderid", "order_id", "txn", "txnid", "tx_id", "authorization"},
)
_AMOUNT_HINTS = frozenset({"amount", "usd", "total", "value", "txn_amount", "payment_amount"})
_STATUS_HINTS = frozenset({"status", "state", "txn_status", "dispute_status", "order_status"})
_IP_HINTS = frozenset({"ip", "ipaddress", "ip_address", "clientip", "buyerip", "sourceip"})
_DEVICE_HINTS = frozenset({"device", "device_id", "deviceid", "fingerprint", "user_agent", "ua"})


def _norm(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(n).lower())


def _best_column(df: pl.DataFrame, hints: frozenset[str]) -> str | None:
    best: tuple[int, str] = (0, "")
    for c in df.columns:
        s = _norm(c)
        score = sum(1 for h in hints if h in s)
        if score > best[0]:
            best = (score, c)
    return best[1] if best[0] > 0 else None


def _status_lower(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.Utf8).str.strip_chars().str.to_lowercase()


def trust_velocity_forensic_scan(
    dataset_path: str | Path,
    *,
    target_amount: Any = None,
    transaction_id: str | None = None,
    max_rows: int | None = 2_000_000,
) -> dict[str, Any]:
    """
    Locate a focal disputed (or high-signal) row, compare the user's completed history (warm-up),
    IP/device reuse, and amount ratio. Emits ``kind: forensic_verdict_card`` for the console UI.
    """
    ta_parsed = parse_loose_amount(target_amount) if target_amount is not None else None
    if ta_parsed is not None and ta_parsed <= 0:
        ta_parsed = None
    target_amount = ta_parsed

    path = Path(dataset_path)
    if not path.is_file():
        return {"ok": False, "error": f"Dataset not found: {path}", "kind": "forensic_verdict_card"}

    read_kw: dict[str, Any] = {"try_parse_dates": True}
    if max_rows is not None:
        read_kw["n_rows"] = max_rows
    try:
        df = pl.read_csv(path, **read_kw)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Failed to read CSV: {exc}", "kind": "forensic_verdict_card"}

    if len(df) == 0:
        return {"ok": False, "error": "Dataset is empty.", "kind": "forensic_verdict_card"}

    user_c = _best_column(df, _USER_HINTS)
    amt_c = _best_column(df, _AMOUNT_HINTS)
    status_c = _best_column(df, _STATUS_HINTS)
    txn_c = _best_column(df, _TXN_HINTS)
    ip_c = _best_column(df, _IP_HINTS)
    dev_c = _best_column(df, _DEVICE_HINTS)

    if not user_c or not amt_c:
        return {
            "ok": False,
            "error": "Need at least user_id and amount columns for Trust vs. Velocity scan.",
            "kind": "forensic_verdict_card",
            "columns_seen": list(df.columns),
        }

    # --- pick focal (disputed) row ---
    focal = pl.DataFrame()
    tid = (transaction_id or "").strip()
    if tid and txn_c and txn_c in df.columns:
        focal = df.filter(pl.col(txn_c).cast(pl.Utf8).str.strip_chars() == tid).head(1)
    if len(focal) == 0 and target_amount is not None:
        focal = df.filter(pl.col(amt_c).cast(pl.Float64, strict=False) == float(target_amount)).head(5)
        if len(focal) > 1 and status_c:
            st = _status_lower(status_c)
            disputed_pat = (
                st.str.contains("dispute")
                | st.str.contains("chargeback")
                | st.str.contains("cbk")
                | st.str.contains("fraud")
                | st.str.contains("reversed")
                | st.str.contains("refund")
                | st.str.contains("unrecognized")
            )
            disputed_first = focal.filter(disputed_pat)
            focal = disputed_first.head(1) if len(disputed_first) > 0 else focal.head(1)
        else:
            focal = focal.head(1)
    if len(focal) == 0 and status_c:
        st = _status_lower(status_c)
        disputed_mask = (
            st.str.contains("dispute")
            | st.str.contains("chargeback")
            | st.str.contains("cbk")
            | st.str.contains("fraud")
            | st.str.contains("reversed")
            | st.str.contains("refund")
            | st.str.contains("unrecognized")
        )
        disputed_all = df.filter(disputed_mask).sort(amt_c, descending=True)
        focal = disputed_all.head(1)
    if len(focal) == 0:
        focal = df.sort(amt_c, descending=True).head(1)

    if len(focal) == 0:
        return {"ok": False, "error": "Could not isolate a focal transaction row.", "kind": "forensic_verdict_card"}

    row0 = focal.row(0, named=True)
    uid = str(row0.get(user_c) or "").strip()
    disputed_amt = float(pl.Series([row0.get(amt_c)]).cast(pl.Float64, strict=False)[0] or 0.0)
    focal_ip = str(row0.get(ip_c) or "").strip() if ip_c else ""
    focal_dev = str(row0.get(dev_c) or "").strip() if dev_c else ""

    if not uid:
        return {"ok": False, "error": "Focal row has empty user id.", "kind": "forensic_verdict_card"}

    user_df = df.filter(pl.col(user_c).cast(pl.Utf8).str.strip_chars() == uid)

    completed = user_df
    if status_c:
        stu = _status_lower(status_c)
        completed = completed.filter(
            stu.is_in(
                [
                    "completed",
                    "settled",
                    "captured",
                    "paid",
                    "success",
                    "closed",
                    "fulfilled",
                ],
            )
        )
    else:
        completed = completed.filter(pl.col(amt_c).cast(pl.Float64, strict=False) < disputed_amt * 0.99)

    n_completed = len(completed)
    avg_completed = 0.0
    if n_completed > 0:
        avg_completed = float(
            completed.select(pl.col(amt_c).cast(pl.Float64, strict=False).mean()).item(),
        )

    ratio = disputed_amt / max(avg_completed, 0.01)
    seasoning = ratio > 10.0 and n_completed >= 3

    prior_same_ip = False
    prior_same_dev = False
    if n_completed > 0:
        if focal_ip and ip_c:
            prior_same_ip = (
                len(completed.filter(pl.col(ip_c).cast(pl.Utf8).str.strip_chars() == focal_ip)) > 0
            )
        if focal_dev and dev_c:
            prior_same_dev = (
                len(completed.filter(pl.col(dev_c).cast(pl.Utf8).str.strip_chars() == focal_dev)) > 0
            )

    ip_device_consistent = prior_same_ip or prior_same_dev

    # Risk score 0–100: ratio drives base; consistency with prior lowers friendly-fraud suspicion slightly
    ratio_score = min(100.0, max(0.0, (ratio - 1.0) * 12.0))
    base = min(95.0, 35.0 + ratio_score)
    if ip_device_consistent:
        base = min(100.0, base + 15.0)
    if seasoning:
        base = min(100.0, base + 12.0)
    risk_score = int(round(max(0.0, min(100.0, base))))

    verdict = "Elevated friendly-fraud / seasoning risk" if seasoning else "Review recommended"
    if seasoning and ip_device_consistent:
        verdict = "High risk — Potential Account Seasoning for Friendly Fraud (device/IP consistent with warm-up)"

    reasoning: list[str] = [
        f"User {uid}: {n_completed} prior completed-like row(s); average completed amount ≈ ${avg_completed:,.2f}.",
        f"Focal transaction amount ${disputed_amt:,.2f} is ~{ratio:.1f}× the historical average among those rows.",
    ]
    if ip_device_consistent:
        reasoning.append(
            "IP/device alignment: disputed activity uses the same infrastructure seen on prior completed orders "
            "(consistent with seasoned-account friendly fraud, not a pure takeover).",
        )
    else:
        reasoning.append("IP/device shift vs prior completed rows — weigh ATO or third-party use in narrative.")

    if seasoning:
        reasoning.append(
            "Label: **Potential Account Seasoning for Friendly Fraud** — dispute is >10× typical prior spend after a warm-up period.",
        )

    focal_payload = {str(k): row0.get(k) for k in df.columns if k in row0}

    return {
        "ok": True,
        "kind": "forensic_verdict_card",
        "risk_score": risk_score,
        "verdict_label": verdict,
        "seasoning_assessment": "Potential Account Seasoning for Friendly Fraud" if seasoning else None,
        "trust_vs_velocity": {
            "completed_tx_count": n_completed,
            "avg_completed_amount": round(avg_completed, 4),
            "focal_amount": disputed_amt,
            "amount_ratio_vs_avg": round(ratio, 4),
        },
        "ip_device_consistency": {
            "prior_completed_shares_ip": prior_same_ip,
            "prior_completed_shares_device": prior_same_dev,
            "interpretation": "consistent_with_warmup" if ip_device_consistent else "shift_or_unknown",
        },
        "focal_transaction": focal_payload,
        "reasoning_bullets": reasoning,
        "columns_used": {
            "user_id": user_c,
            "amount": amt_c,
            "status": status_c,
            "transaction_id": txn_c,
            "ip": ip_c,
            "device": dev_c,
        },
    }
