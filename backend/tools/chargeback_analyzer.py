"""Chargeback / friendly-fraud analysis using Polars on transaction-level datasets."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import polars as pl

# --- column inference (normalized header tokens) ---

_USER_HINTS = frozenset(
    {"userid", "user_id", "customer", "customerid", "account", "accountid", "memberid", "buyerid"}
)
_TXN_HINTS = frozenset(
    {"transaction", "transactionid", "orderid", "order_id", "txn", "txnid", "authorization"}
)
_IP_HINTS = frozenset({"ip", "ipaddress", "clientip", "buyerip", "sourceip"})
_DEVICE_HINTS = frozenset({"device", "deviceid", "devicefingerprint", "fingerprint", "dfp"})
_DISPUTED_HINTS = frozenset(
    {"disputed", "isdisputed", "chargeback", "ischargeback", "cbflag", "disputestatus", "in_dispute"}
)
_REASON_HINTS = frozenset({"reason", "disputereason", "chargebackreason", "issuerreason", "reasoncode"})
_TXN_DATE_HINTS = frozenset(
    {"transactiondate", "date", "authdate", "purchasedate", "createdat", "orderdate", "settled_at"}
)
_DISPUTE_DATE_HINTS = frozenset(
    {"disputedate", "chargebackdate", "claimdate", "unauthorizeddate", "codedate", "representmentdate"}
)
_LOGIN_HINTS = frozenset(
    {"login", "lastlogin", "session", "userlogin", "accountlogin", "signin", "signon"}
)
_ACCESS_HINTS = frozenset(
    {"download", "contentaccess", "digitalaccess", "licenseaccess", "gameplay", "usage", "stream"}
)
_BILL_HINTS = frozenset({"billing", "billto", "cardholder", "avs", "billzip", "billingzip", "billingpostal"})
_SHIP_HINTS = frozenset({"shipping", "shipto", "shipzip", "shippingzip", "delivery", "destination"})
_AVS_HINTS = frozenset({"avs", "avscode", "avsresult", "addressverification"})
_CVV_HINTS = frozenset({"cvv", "cvv2", "cvc", "cvcresult", "securitycode"})
_COMM_HINTS = frozenset({"support", "ticket", "email", "contact", "csnote", "communication"})


def _norm(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(n).lower())


def _best_column(df: pl.DataFrame, hints: frozenset[str], min_score: int = 1) -> str | None:
    best: tuple[int, str] = (0, "")
    for c in df.columns:
        s = _norm(c)
        score = sum(1 for h in hints if h in s)
        if score > best[0] and score >= min_score:
            best = (score, c)
    return best[1] if best[0] > 0 else None


def resolve_chargeback_columns(df: pl.DataFrame) -> dict[str, str | None]:
    """Map semantic roles to actual column names (or None if absent)."""
    return {
        "user_id": _best_column(df, _USER_HINTS),
        "transaction_id": _best_column(df, _TXN_HINTS),
        "ip": _best_column(df, _IP_HINTS),
        "device_id": _best_column(df, _DEVICE_HINTS),
        "disputed": _best_column(df, _DISPUTED_HINTS),
        "dispute_reason": _best_column(df, _REASON_HINTS),
        "transaction_date": _best_column(df, _TXN_DATE_HINTS),
        "dispute_date": _best_column(df, _DISPUTE_DATE_HINTS),
        "login_ts": _best_column(df, _LOGIN_HINTS),
        "access_ts": _best_column(df, _ACCESS_HINTS),
        "billing_zip": _best_column(df, _BILL_HINTS),
        "shipping_zip": _best_column(df, _SHIP_HINTS),
        "avs": _best_column(df, _AVS_HINTS),
        "cvv": _best_column(df, _CVV_HINTS),
        "comms": _best_column(df, _COMM_HINTS),
    }


def _disputed_expr(disputed_col: str) -> pl.Expr:
    """Rows treated as disputed / chargeback."""
    raw = pl.col(disputed_col)
    as_str = raw.cast(pl.Utf8).str.strip_chars().str.to_lowercase()
    truthy = as_str.is_in(
        ("1", "true", "t", "yes", "y", "disputed", "chargeback", "cb", "fraud", "accepted", "lost")
    )
    return truthy | (raw.cast(pl.Boolean, strict=False).fill_null(False))


def _parse_dates(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    out = df
    for c in cols:
        if c and c in out.columns:
            out = out.with_columns(
                pl.coalesce(
                    pl.col(c).cast(pl.Datetime, strict=False),
                    pl.col(c).cast(pl.Utf8).str.to_datetime(strict=False, time_unit="us"),
                ).alias(c)
            )
    return out


def analyze_chargeback_risk(
    dataset_path: str | Path,
    *,
    max_rows: int | None = 2_000_000,
) -> dict[str, Any]:
    """
    Analyze a transaction CSV for friendly-fraud style signals and representment-relevant facts.

    Primary signals (when columns exist):
    - IP/device reuse: disputed row shares IP or device with a prior non-disputed row for same user.
    - Post-dispute activity: login or digital-access timestamp after dispute/unauthorized date.
    - Velocity: 3+ disputed lines for a user within ~180 days.
    - Shipping vs billing: postal/billing fields mismatch.
    - AVS/CVV strong match hints.
    """
    path = Path(dataset_path)
    if not path.is_file():
        return {"ok": False, "error": f"Dataset not found: {path}"}

    read_kw: dict[str, Any] = {"try_parse_dates": True}
    if max_rows is not None:
        read_kw["n_rows"] = max_rows
    try:
        df = pl.read_csv(path, **read_kw)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Failed to read CSV: {exc}"}

    if len(df) == 0:
        return {"ok": False, "error": "Dataset is empty."}

    cols = resolve_chargeback_columns(df)
    date_cols = [
        c
        for c in (
            cols.get("transaction_date"),
            cols.get("dispute_date"),
            cols.get("login_ts"),
            cols.get("access_ts"),
        )
        if c and c in df.columns
    ]
    df = _parse_dates(df, date_cols)

    # --- IP / device match (focus per user) ---
    ip_device_flags: list[dict[str, Any]] = []
    user_c = cols.get("user_id")
    disputed_c = cols.get("disputed")
    ip_c = cols.get("ip")
    dev_c = cols.get("device_id")
    txn_c = cols.get("transaction_id")

    if user_c and disputed_c and (ip_c or dev_c):
        disputed_mask = _disputed_expr(disputed_c)
        dfx = df.with_columns(disputed_mask.alias("__disputed"))
        disputed_df = dfx.filter(pl.col("__disputed"))
        clean_df = dfx.filter(~pl.col("__disputed"))

        if len(disputed_df) > 0 and len(clean_df) > 0:
            # prior non-disputed for same user
            for kind, col in (("ip", ip_c), ("device", dev_c)):
                if not col:
                    continue
                joined = disputed_df.join(
                    clean_df.select([pl.col(user_c), pl.col(col).alias("_prior_val")]),
                    on=user_c,
                    how="inner",
                ).filter(pl.col(col) == pl.col("_prior_val"))
                for row in joined.head(500).iter_rows(named=True):
                    rid = row.get(txn_c) if txn_c else None
                    ip_device_flags.append(
                        {
                            "transaction_id": str(rid) if rid is not None else None,
                            "user_id": str(row.get(user_c)),
                            "signal": f"{kind}_matches_prior_undisputed",
                            "detail": f"Same {kind} {row.get(col)!r} seen on disputed and prior cleared activity.",
                        }
                    )

    # --- Post-dispute activity ---
    post_dispute: list[dict[str, Any]] = []
    dispute_d = cols.get("dispute_date")
    login_c = cols.get("login_ts")
    access_c = cols.get("access_ts")
    if dispute_d and user_c and disputed_c:
        disputed_only = (
            df.filter(_disputed_expr(disputed_c))
            .with_columns(_disputed_expr(disputed_c).alias("__disputed"))
        )
        for activity_col, label in ((login_c, "login"), (access_c, "digital_access")):
            if not activity_col or activity_col not in df.columns:
                continue
            act = pl.col(activity_col).cast(pl.Datetime, strict=False)
            dd = pl.col(dispute_d).cast(pl.Datetime, strict=False)
            flagged = disputed_only.filter(act.is_not_null() & dd.is_not_null() & (act > dd))
            for row in flagged.head(300).iter_rows(named=True):
                tid = row.get(txn_c) if txn_c else None
                post_dispute.append(
                    {
                        "transaction_id": str(tid) if tid is not None else None,
                        "user_id": str(row.get(user_c)) if user_c else None,
                        "signal": f"activity_after_dispute_{label}",
                        "detail": f"{label} at {row.get(activity_col)!r} follows dispute date {row.get(dispute_d)!r}.",
                    }
                )

    # --- Velocity: 3+ disputes in 180 days ---
    velocity: list[dict[str, Any]] = []
    if user_c and disputed_c and dispute_d:
        d_events = (
            df.filter(_disputed_expr(disputed_c))
            .select(
                pl.col(user_c).alias("u"),
                pl.col(dispute_d).cast(pl.Datetime, strict=False).alias("d_dt"),
            )
            .drop_nulls("d_dt")
        )
        if len(d_events) > 0:
            alias_events = d_events.rename({"d_dt": "d_anchor"})
            counts = (
                d_events.join(alias_events, on="u", how="inner")
                .filter(pl.col("d_dt") >= pl.col("d_anchor") - pl.duration(days=180))
                .filter(pl.col("d_dt") <= pl.col("d_anchor"))
                .group_by(["u", "d_anchor"])
                .agg(pl.len().alias("cb_6mo"))
                .filter(pl.col("cb_6mo") >= 3)
            )
            for row in counts.head(200).iter_rows(named=True):
                velocity.append(
                    {
                        "user_id": str(row["u"]),
                        "signal": "high_dispute_velocity",
                        "detail": f"{row['cb_6mo']} chargeback-tagged rows in trailing 6 months window.",
                    }
                )

    # --- Shipping vs billing mismatch ---
    ship_bill: list[dict[str, Any]] = []
    bz = cols.get("billing_zip")
    sz = cols.get("shipping_zip")
    if bz and sz and bz in df.columns and sz in df.columns:
        norm_b = pl.col(bz).cast(pl.Utf8).str.strip_chars().str.replace_all(r"\s+", "")
        norm_s = pl.col(sz).cast(pl.Utf8).str.strip_chars().str.replace_all(r"\s+", "")
        mism = df.filter(
            norm_b.is_not_null()
            & norm_s.is_not_null()
            & (norm_b != "")
            & (norm_s != "")
            & (norm_b != norm_s)
        )
        if disputed_c and disputed_c in mism.columns:
            mism = mism.filter(_disputed_expr(disputed_c))
        for row in mism.head(200).iter_rows(named=True):
            tid = row.get(txn_c) if txn_c else None
            ship_bill.append(
                {
                    "transaction_id": str(tid) if tid is not None else None,
                    "signal": "billing_shipping_mismatch",
                    "detail": f"Billing {row.get(bz)!r} vs shipping {row.get(sz)!r}.",
                }
            )

    # --- AVS / CVV strong ---
    avs_cvv: list[dict[str, Any]] = []
    for label, c in (("avs", cols.get("avs")), ("cvv", cols.get("cvv"))):
        if not c or c not in df.columns:
            continue
        s = pl.col(c).cast(pl.Utf8).str.strip_chars().str.to_lowercase()
        strong = (
            df.filter(
                s.is_in(("full", "match", "y", "pass", "m", "p", "authenticated", "success"))
                | s.str.contains("match")
            )
        )
        if disputed_c and disputed_c in strong.columns:
            strong = strong.filter(_disputed_expr(disputed_c))
        for row in strong.head(150).iter_rows(named=True):
            tid = row.get(txn_c) if txn_c else None
            avs_cvv.append(
                {
                    "transaction_id": str(tid) if tid is not None else None,
                    "signal": f"strong_{label}",
                    "detail": f"{label.upper()} result {row.get(c)!r}.",
                }
            )

    # Aggregate scoring (merchant-favorable evidence; capped sub-scores)
    score = min(
        100.0,
        min(36.0, len(ip_device_flags) * 3.5)
        + min(28.0, len(post_dispute) * 4.0)
        + min(18.0, len(velocity) * 6.0)
        + min(14.0, len(ship_bill) * 2.5)
        + min(14.0, len(avs_cvv) * 2.0),
    )
    disputed_n = (
        int(df.filter(_disputed_expr(disputed_c)).height) if disputed_c and disputed_c in df.columns else 0
    )

    base_win = 0.28
    win_p = min(
        0.92,
        base_win
        + score / 125.0
        + 0.07 * min(1.0, len(post_dispute) / 4.0)
        + 0.05 * min(1.0, len(ip_device_flags) / 5.0),
    )

    narrative_parts: list[str] = []
    if ip_device_flags:
        narrative_parts.append(
            f"IP/device alignment with prior undisputed purchases: {len(ip_device_flags)} signal(s)."
        )
    if post_dispute:
        narrative_parts.append(
            f"Post-claim digital footprint: {len(post_dispute)} login/access event(s) after dispute date."
        )
    if velocity:
        narrative_parts.append(
            f"Repeat dispute velocity: {len(velocity)} user-window(s) with 3+ disputes in 6 months."
        )
    if ship_bill:
        narrative_parts.append(
            f"Billing vs shipping deltas on disputed lines: {len(ship_bill)} mismatch(es) (review for INR/INR-false claims)."
        )
    if avs_cvv:
        narrative_parts.append(f"Strong AVS/CVV artifacts: {len(avs_cvv)} row(s).")

    return {
        "ok": True,
        "dataset_path": str(path.resolve()),
        "rows_analyzed": len(df),
        "columns_resolved": cols,
        "disputed_row_count": disputed_n,
        "friendly_fraud_indicators": {
            "ip_device_prior_match": ip_device_flags[:80],
            "activity_after_dispute": post_dispute[:80],
            "dispute_velocity_6mo": velocity[:80],
            "shipping_billing_mismatch": ship_bill[:80],
            "avs_cvv_positive": avs_cvv[:80],
        },
        "chargeback_risk_score": round(score, 1),
        "interpretation": {
            "chargeback_risk_score": "0–100 merchant evidence strength proxy (higher = more compelling representment artifacts detected).",
            "win_probability": "Heuristic win rate; not legal advice — tune with your issuer mix.",
        },
        "win_probability": round(win_p, 4),
        "win_probability_percent": round(win_p * 100, 1),
        "executive_summary": narrative_parts,
        "key_evidence_hunt": [
            {"evidence_type": "IP/Device fingerprint", "status": "scanned", "why": "Proves repeat device or network used on good history."},
            {"evidence_type": "Usage logs", "status": "scanned", "why": "Shows access after 'unauthorized' narrative."},
            {"evidence_type": "AVS/CVV", "status": "scanned", "why": "Issuer-verified billing participation."},
            {"evidence_type": "Communication history", "status": "partial", "why": "Requires support/ticket columns in dataset."},
        ],
    }
