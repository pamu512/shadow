"""Dataset schema helpers for agents and code review."""
from __future__ import annotations

from pathlib import Path

import polars as pl


def describe_csv(path: str | Path, sample_rows: int = 5) -> dict:
    p = Path(path)
    if not p.is_file():
        return {"error": f"Dataset not found: {path}"}
    df = pl.read_csv(p, try_parse_dates=True, n_rows=max(sample_rows, 50))
    sample = df.head(sample_rows)
    return {
        "path": str(p.resolve()),
        "columns": [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns],
        "n_rows_hint": len(df),
        "sample_rows": sample.to_dicts(),
    }
