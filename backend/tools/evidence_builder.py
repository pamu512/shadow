"""Representment / dispute evidence manifest from transaction records."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import polars as pl

from backend.tools.chargeback_analyzer import resolve_chargeback_columns

_TXN_HINTS = re.compile(r"transaction|order|txn|authorization|auth", re.I)


def _find_transaction_column(df: pl.DataFrame) -> str | None:
    cols = resolve_chargeback_columns(df)
    if cols.get("transaction_id"):
        return cols["transaction_id"]
    best = None
    for c in df.columns:
        if _TXN_HINTS.search(c):
            best = c
            break
    return best


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def build_representment_manifest(
    transaction_id: str,
    dataset_path: str | Path,
    *,
    max_rows: int | None = 2_000_000,
) -> dict[str, Any]:
    """
    Build a Representment Manifest (JSON) for a single transaction id.

    Pulls available fields from the case CSV into structured sections:
    - proof_of_service: IP logs, login timestamps, digital access / downloads
    - proof_of_delivery: carrier / tracking / signed delivery placeholders from row data
    - policy_acknowledgment: terms & conditions acceptance timestamp when present
    - communication_history: support / email columns when present
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

    txn_col = _find_transaction_column(df)
    if not txn_col or txn_col not in df.columns:
        return {"ok": False, "error": "Could not resolve a transaction / order id column.", "columns": df.columns}

    match = df.filter(pl.col(txn_col).cast(pl.Utf8).str.strip_chars() == str(transaction_id).strip())
    if len(match) == 0:
        return {"ok": False, "error": f"transaction_id {transaction_id!r} not found in dataset."}

    resolved = resolve_chargeback_columns(df)
    row = match.to_dicts()[0]
    flat = _row_to_dict(row)

    def pick(*keys: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in keys:
            c = resolved.get(k)
            if c and c in flat and flat[c] is not None:
                out[c] = flat[c]
        return out

    # Map semantic slots to manifest (null when column missing)
    ip_logs = pick("ip")
    login_fields = pick("login_ts")
    digital_usage = pick("access_ts")

    tracking_candidates = {
        k: flat[k]
        for k in flat
        if re.search(r"track|carrier|ups|fedex|usps|delivery|pod|signed", str(k), re.I)
    }
    ship = pick("shipping_zip")
    bill = pick("billing_zip")

    tos_candidates = {
        k: flat[k]
        for k in flat
        if re.search(r"terms|tos|policy|accept|checkbox|consent", str(k), re.I)
    }

    comms = pick("comms")
    if not comms:
        comms = {
            k: flat[k]
            for k in flat
            if re.search(r"support|ticket|email|cs_|contact", str(k), re.I)
        }

    avs_cvv = {**pick("avs"), **pick("cvv")}

    manifest: dict[str, Any] = {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "transaction_id": str(transaction_id),
        "transaction_column_used": txn_col,
        "source_row": flat,
        "representment_manifest_version": "1.0",
        "proof_of_service": {
            "ip_logs": ip_logs or None,
            "login_timestamps": login_fields or None,
            "download_or_digital_access_records": digital_usage or None,
            "notes": "Populate issuer-specific exhibits (gateway logs, CDN logs) if not in CSV.",
        },
        "proof_of_delivery": {
            "carrier_tracking_fields": tracking_candidates or None,
            "shipping_postal": ship or None,
            "billing_postal": bill or None,
            "signed_delivery_status": next(
                (tracking_candidates[k] for k in tracking_candidates if re.search(r"signed|pod|delivered", str(k), re.I)),
                None,
            ),
            "notes": "Attach carrier POD PDFs / BOLs not stored in this row-level extract.",
        },
        "policy_acknowledgment": {
            "terms_and_conditions_timestamp": tos_candidates or None,
            "notes": "Checkout checkbox timestamps strengthen consent narratives.",
        },
        "authentication": {
            "avs_cvv_fields": avs_cvv or None,
        },
        "communication_history": comms or None,
    }

    return manifest


def write_representment_package_zip(
    manifest: dict[str, Any],
    dest: str | Path,
    *,
    summary_text: str | None = None,
) -> Path:
    """Write manifest.json + REPRESENTMENT_SUMMARY.txt into a zip on disk."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(dest, "w", ZIP_DEFLATED) as zf:
        _write_package_entries(zf, manifest, summary_text)
    return dest


def _write_package_entries(zf: ZipFile, manifest: dict[str, Any], summary_text: str | None) -> None:
    zf.writestr(
        "representment_manifest.json",
        json.dumps(manifest, indent=2, default=str),
    )
    lines = [
        "Shadow — Representment package",
        f"Transaction: {manifest.get('transaction_id')}",
        "",
        summary_text or "See representment_manifest.json for structured exhibits.",
    ]
    zf.writestr("REPRESENTMENT_SUMMARY.txt", "\n".join(lines))


def representment_package_bytes(
    manifest: dict[str, Any],
    *,
    summary_text: str | None = None,
) -> bytes:
    """Zip archive bytes (manifest + summary) for HTTP download."""
    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        _write_package_entries(zf, manifest, summary_text)
    return buf.getvalue()
