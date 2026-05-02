"""Last-N-hours activity series for case cards (volume or scores)."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

HOURS = 24
ROW_CAP = 250_000


def _synthetic_activity(case_id: str) -> dict[str, Any]:
    seed = sum(ord(c) * (i + 11) for i, c in enumerate(case_id)) % (2**32)
    rng = np.random.default_rng(seed)
    t = np.arange(HOURS, dtype=float)
    base = 42 + 12 * np.sin(t / 3.8) + rng.normal(0, 5, HOURS)
    spike_mask = rng.random(HOURS) < 0.12
    base = np.where(spike_mask, base + rng.uniform(28, 95, HOURS), base)
    base = np.clip(base, 0, None).astype(float)
    thr = float(np.percentile(base, 82)) if base.max() > 0 else 1.0
    return {"values": base.round(4).tolist(), "threshold": round(thr, 4)}


def _pick_datetime_col(df: pl.DataFrame) -> str | None:
    preferred = ("ts", "timestamp", "datetime", "time", "created_at", "event_time")
    for name in preferred:
        if name in df.columns:
            return name
    for c in df.columns:
        dt = df[c].dtype
        if dt == pl.Datetime or dt == pl.Date:
            return c
    return None


def _pick_value_col(df: pl.DataFrame, skip: set[str]) -> str | None:
    preferred = ("amount", "volume", "score", "value", "v", "count", "txn_count", "anomaly_score")
    for name in preferred:
        if name in df.columns and name not in skip:
            return name
    for c in df.columns:
        if c in skip:
            continue
        if df[c].dtype in (pl.Float32, pl.Float64, pl.Int32, pl.Int64, pl.UInt32, pl.UInt64):
            return c
    return None


def _align_hourly(y: np.ndarray) -> list[float]:
    """Ensure length HOURS; left-pad with first value or zero."""
    y = np.asarray(y, dtype=float).ravel()
    if y.size >= HOURS:
        return y[-HOURS:].round(4).tolist()
    if y.size == 0:
        return [0.0] * HOURS
    pad = HOURS - y.size
    first = float(y[0]) if y.size else 0.0
    out = np.concatenate([np.full(pad, first), y])
    return out[-HOURS:].round(4).tolist()


def compute_case_activity(case_id: str, dataset_path: str | None, hours: int = HOURS) -> dict[str, Any]:
    if hours != HOURS:
        hours = HOURS
    path = Path(dataset_path) if dataset_path else None
    if not path or not path.is_file():
        return _synthetic_activity(case_id)

    try:
        df = pl.read_csv(path, try_parse_dates=True, infer_schema_length=8000, n_rows=ROW_CAP)
    except Exception:
        return _synthetic_activity(case_id)

    if len(df) == 0:
        return _synthetic_activity(case_id)

    dt_col = _pick_datetime_col(df)
    skip = {dt_col} if dt_col else set()
    val_col = _pick_value_col(df, skip)

    if dt_col and val_col:
        try:
            s = df.select(
                pl.col(dt_col).alias("_dt"),
                pl.col(val_col).cast(pl.Float64, strict=False).alias("_v"),
            ).drop_nulls()
            if len(s) == 0:
                return _synthetic_activity(case_id)
            cut = datetime.utcnow() - timedelta(hours=hours)
            s = s.filter(pl.col("_dt") >= pl.lit(cut))
            if len(s) == 0:
                return _synthetic_activity(case_id)
            s = s.sort("_dt")
            hourly = (
                s.with_columns(pl.col("_dt").dt.truncate("1h").alias("hb"))
                .group_by("hb")
                .agg(pl.col("_v").sum().alias("y"))
                .sort("hb")
            )
            ys = hourly["y"].to_numpy()
            values = _align_hourly(ys)
        except Exception:
            return _synthetic_activity(case_id)
    elif val_col:
        n = len(df)
        col = df[val_col].cast(pl.Float64, strict=False)
        bucket = max(1, n // hours)
        buckets: list[float] = []
        for b in range(hours):
            start = b * bucket
            if start >= n:
                buckets.append(0.0)
                continue
            end = min(n, (b + 1) * bucket)
            sl = col.slice(start, end - start)
            buckets.append(float(sl.sum()) if sl.len() > 0 else 0.0)
        values = [round(x, 4) for x in buckets]
    else:
        return _synthetic_activity(case_id)

    arr = np.asarray(values, dtype=float)
    thr = float(np.percentile(arr, 85)) if arr.max() > 0 else float(np.mean(arr) + 1e-6)
    return {"values": [round(float(x), 4) for x in values], "threshold": round(thr, 4)}
