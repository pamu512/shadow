"""Generate Polars / data.table scaffolds."""
from __future__ import annotations

from typing import Literal


def _default_columns() -> list[dict[str, str]]:
    return [
        {"name": "transaction_id", "dtype": "Utf8"},
        {"name": "amount", "dtype": "Float64"},
        {"name": "ts", "dtype": "Datetime"},
    ]


def generate_scaffold(
    language: Literal["python", "r"],
    intent: str,
    columns: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    cols = columns or _default_columns()
    if language == "python":
        col_comments = "\n".join(f"# - {c['name']}: {c.get('dtype', '')}" for c in cols)
        code = f'''"""Auto-generated Polars pipeline.
Intent: {intent}

Schema hint:
{col_comments}

The sandbox injects DATASET_PATH (from FRAUD_DATASET_PATH) before this code; no import os needed.
"""
import polars as pl

DATA_PATH = DATASET_PATH or "workspace/datasets/sample.csv"
df = pl.read_csv(DATA_PATH, try_parse_dates=True)
result = (
    df.lazy()
    .with_columns([
        # Add engineered features here
    ])
    .group_by([])
    .agg([])
)
out = result.collect()
print(out.head())
# Optional: write PNGs to PLOT_DIR (injected by sandbox) if needed
'''
        explanation = "Polars LazyFrame scaffold with read_csv and placeholders."
        return code, explanation

    col_comment_r = "\n".join(f"# - {c['name']}" for c in cols)
    code = f'# Intent: {intent}\n# Columns:\n{col_comment_r}\n\nlibrary(data.table)\npath <- Sys.getenv("FRAUD_DATASET_PATH", unset = "workspace/datasets/sample.csv")\ndt <- fread(path)\n# Add transformations with `:=` and keyed joins\nprint(head(dt))\n# png(file.path(Sys.getenv("FRAUD_PLOT_DIR"), "plot.png")); plot(1); dev.off()\n'
    explanation = "data.table fread scaffold with placeholders."
    return code, explanation
