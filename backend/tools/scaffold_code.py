"""Generate Polars / data.table scaffolds with intent-aware structure."""
from __future__ import annotations

import re
from typing import Literal, NamedTuple


def _default_columns() -> list[dict[str, str]]:
    return [
        {"name": "transaction_id", "dtype": "Utf8"},
        {"name": "amount", "dtype": "Float64"},
        {"name": "ts", "dtype": "Datetime"},
    ]


class _Profile(NamedTuple):
    id: str
    label: str


_PROFILE_GENERIC = _Profile("generic", "general exploration")
_PROFILE_VELOCITY = _Profile("velocity", "entity velocity / concentration")
_PROFILE_SEGMENT = _Profile("segment", "segment or cohort breakdown")
_PROFILE_TIME_SERIES = _Profile("time_series", "temporal aggregation")
_PROFILE_CHARGEBACK = _Profile("chargeback", "chargeback or dispute rates")
_PROFILE_ANOMALY = _Profile("anomaly", "outlier / z-score style ranking")
_PROFILE_NETWORK = _Profile("network", "shared-attribute linkage")


def _intent_profile(intent: str) -> _Profile:
    s = intent.lower()
    if any(
        k in s
        for k in (
            "network",
            "graph",
            "fraud ring",
            "linkage",
            "shared device",
            "shared ip",
            "shared card",
            "entity link",
            "co-occurrence",
        )
    ):
        return _PROFILE_NETWORK
    if any(k in s for k in ("chargeback", "dispute", "representment", "cb rate", "charge back")):
        return _PROFILE_CHARGEBACK
    if any(k in s for k in ("anomal", "outlier", "unusual", "z-score", "zscore")):
        return _PROFILE_ANOMALY
    if any(
        k in s
        for k in (
            "velocity",
            "frequency",
            "txn count",
            "transaction count",
            "transactions per",
            "burst",
            "rapid",
        )
    ):
        return _PROFILE_VELOCITY
    if any(
        k in s
        for k in (
            "time series",
            "timeseries",
            "over time",
            " daily",
            "daily ",
            "hourly",
            "weekly",
            "monthly",
            "trend",
            "calendar",
        )
    ):
        return _PROFILE_TIME_SERIES
    if any(
        k in s
        for k in (
            "segment",
            "cohort",
            "breakdown",
            "stratif",
            "by merchant",
            "by category",
            " by channel",
            "slice",
        )
    ):
        return _PROFILE_SEGMENT
    return _PROFILE_GENERIC


def _pick_column(cols: list[dict[str, str]], *substrings: str) -> str | None:
    for c in cols:
        name = c["name"]
        low = name.lower()
        if any(sub in low for sub in substrings):
            return name
    return None


class _ColumnHints(NamedTuple):
    user: str
    amount: str
    ts: str
    segment: str
    link: str


def _column_hints(cols: list[dict[str, str]]) -> _ColumnHints:
    user = (
        _pick_column(cols, "user", "account", "customer", "payer", "wallet", "entity", "cardholder")
        or "user_id"
    )
    amount = _pick_column(cols, "amount", "amt", "value", "total", "usd", "payment") or "amount"
    ts = _pick_column(cols, "ts", "time", "timestamp", "created", "date", "txn_time") or "ts"
    segment = (
        _pick_column(cols, "merchant", "category", "channel", "segment", "product", "mcc", "country")
        or "merchant_id"
    )
    link = _pick_column(cols, "device", "ip", "card", "token", "cookie", "email", "phone") or "device_id"
    return _ColumnHints(user=user, amount=amount, ts=ts, segment=segment, link=link)


def _safe_doc_intent(intent: str) -> str:
    return intent.replace('"""', '"').strip()


def _build_python(profile: _Profile, intent: str, cols: list[dict[str, str]]) -> tuple[str, str]:
    doc = _safe_doc_intent(intent)
    col_comments = "\n".join(f"# - {c['name']}: {c.get('dtype', '')}" for c in cols)
    h = _column_hints(cols)
    uc, ac, tc, sc, lc = h.user, h.amount, h.ts, h.segment, h.link

    if profile.id == "velocity":
        body = f'''result = (
    df.lazy()
    .group_by("{uc}")
    .agg(
        [
            pl.len().alias("txn_count"),
            pl.col("{ac}").sum().alias("volume"),
            pl.col("{ac}").mean().alias("avg_{ac}"),
            pl.col("{ac}").max().alias("max_{ac}"),
        ]
    )
    .sort("txn_count", descending=True)
)'''
        expl = f"Polars scaffold for {_PROFILE_VELOCITY.label}: group_by `{uc}`, counts and `{ac}` stats."
    elif profile.id == "segment":
        body = f'''result = (
    df.lazy()
    .group_by("{sc}")
    .agg(
        [
            pl.len().alias("txn_count"),
            pl.col("{ac}").sum().alias("volume"),
            pl.col("{ac}").mean().alias("avg_{ac}"),
        ]
    )
    .sort("volume", descending=True)
)'''
        expl = f"Polars scaffold for {_PROFILE_SEGMENT.label}: group_by `{sc}`."
    elif profile.id == "time_series":
        body = f'''result = (
    df.lazy()
    .with_columns(
        pl.col("{tc}").cast(pl.Datetime, strict=False).dt.truncate("1d").alias("day")
    )
    .group_by("day")
    .agg([pl.len().alias("txns"), pl.col("{ac}").sum().alias("volume")])
    .sort("day")
)'''
        expl = f"Polars scaffold for {_PROFILE_TIME_SERIES.label}: daily rollups on `{tc}`."
    elif profile.id == "chargeback":
        body = f'''# If you have a binary label column, uncomment and rename (e.g. is_chargeback).
# label = "is_chargeback"
result = (
    df.lazy()
    .group_by("{sc}")
    .agg(
        [
            pl.len().alias("total_txns"),
            # pl.sum(label).alias("chargebacks"),
        ]
    )
    # .with_columns((pl.col("chargebacks") / pl.col("total_txns")).alias("cb_rate"))
    .sort("total_txns", descending=True)
)'''
        expl = (
            f"Polars scaffold for {_PROFILE_CHARGEBACK.label}: segment totals; "
            "uncomment label lines when a chargeback flag exists."
        )
    elif profile.id == "anomaly":
        body = f'''_mean = pl.col("{ac}").mean()
_std = pl.col("{ac}").std(ddof=1)
result = (
    df.lazy()
    .with_columns(
        pl.when(_std > 0)
        .then((pl.col("{ac}") - _mean) / _std)
        .otherwise(None)
        .alias("amount_z")
    )
    .sort("amount_z", descending=True, nulls_last=True)
)'''
        expl = f"Polars scaffold for {_PROFILE_ANOMALY.label}: global z-score on `{ac}` then sort."
    elif profile.id == "network":
        body = f'''# Shared `{lc}` across many `{uc}` values — tighten filters to your schema.
result = (
    df.lazy()
    .filter(pl.col("{uc}").is_not_null() & pl.col("{lc}").is_not_null())
    .group_by("{lc}")
    .agg(pl.col("{uc}").n_unique().alias("distinct_users"))
    .filter(pl.col("distinct_users") > 1)
    .sort("distinct_users", descending=True)
)'''
        expl = f"Polars scaffold for {_PROFILE_NETWORK.label}: `{lc}` hubs by distinct `{uc}`."
    else:
        body = """result = df.lazy()
out = result.collect()
print(out.head(25))
try:
    print(out.describe())
except Exception:
    pass"""
        expl = f"Polars scaffold for {_PROFILE_GENERIC.label}: sample rows and describe()."

    if profile.id != "generic":
        code = f'''"""Auto-generated Polars pipeline.
Intent: {doc}
Profile: {profile.label}

Schema hint:
{col_comments}

The sandbox injects DATASET_PATH (from FRAUD_DATASET_PATH) before this code; no import os needed.
"""
import polars as pl

DATA_PATH = DATASET_PATH or "workspace/datasets/sample.csv"
df = pl.read_csv(DATA_PATH, try_parse_dates=True)
{body}
out = result.collect()
print(out.head(50))
# Optional: plt.savefig(os.path.join(PLOT_DIR, "out.png")) — PLOT_DIR injected in sandbox
'''
    else:
        code = f'''"""Auto-generated Polars pipeline.
Intent: {doc}
Profile: {profile.label}

Schema hint:
{col_comments}

The sandbox injects DATASET_PATH (from FRAUD_DATASET_PATH) before this code; no import os needed.
"""
import polars as pl

DATA_PATH = DATASET_PATH or "workspace/datasets/sample.csv"
df = pl.read_csv(DATA_PATH, try_parse_dates=True)
{body}
'''

    return code, expl


def _sanitize_r_ident(name: str) -> str:
    """Return a safe symbol fragment for glue in comments; data.table uses strings for fread."""
    if re.match(r"^[A-Za-z._][A-Za-z0-9._]*$", name):
        return name
    return re.sub(r"[^A-Za-z0-9._]+", "_", name)[:64] or "col"


def _build_r(profile: _Profile, intent: str, cols: list[dict[str, str]]) -> tuple[str, str]:
    doc = _safe_doc_intent(intent).replace("\n", " ")
    col_comment_r = "\n".join(f"# - {c['name']}" for c in cols)
    h = _column_hints(cols)
    uc, ac, tc, sc, lc = (_sanitize_r_ident(x) for x in (h.user, h.amount, h.ts, h.segment, h.link))

    if profile.id == "velocity":
        snippet = f'dt_out <- dt[, .(txn_count = .N, volume = sum({ac}, na.rm = TRUE)), by = "{uc}"]\nsetorder(dt_out, -txn_count)\nprint(head(dt_out, 50))'
        expl = f"data.table scaffold for {_PROFILE_VELOCITY.label}: by `{uc}`."
    elif profile.id == "segment":
        snippet = f'dt_out <- dt[, .(txn_count = .N, volume = sum({ac}, na.rm = TRUE)), by = "{sc}"]\nsetorder(dt_out, -volume)\nprint(head(dt_out, 50))'
        expl = f"data.table scaffold for {_PROFILE_SEGMENT.label}: by `{sc}`."
    elif profile.id == "time_series":
        snippet = (
            f'dt[, day := as.IDate(get("{tc}"))]\n'
            f'dt_out <- dt[, .(txns = .N, volume = sum({ac}, na.rm = TRUE)), by = day]\n'
            f'setorder(dt_out, day)\nprint(head(dt_out, 50))'
        )
        expl = f"data.table scaffold for {_PROFILE_TIME_SERIES.label}: daily by `{tc}`."
    elif profile.id == "chargeback":
        snippet = (
            f'# Add label column name, e.g. is_cb, then:\n'
            f'# dt_out <- dt[, .(total = .N, cb = sum(is_cb, na.rm = TRUE)), by = "{sc}"]\n'
            f'# dt_out[, cb_rate := cb / total]\n'
            f'dt_out <- dt[, .(total_txns = .N), by = "{sc}"]\nsetorder(dt_out, -total_txns)\nprint(head(dt_out, 50))'
        )
        expl = f"data.table scaffold for {_PROFILE_CHARGEBACK.label}: segment counts + commented CB rate."
    elif profile.id == "anomaly":
        snippet = (
            f'dt[, amount_z := ({ac} - mean({ac}, na.rm = TRUE)) / sd({ac}, na.rm = TRUE)]\n'
            f'setorder(dt, -amount_z, na.last = TRUE)\nprint(head(dt, 50))'
        )
        expl = f"data.table scaffold for {_PROFILE_ANOMALY.label}: z-score on `{ac}`."
    elif profile.id == "network":
        snippet = (
            f'dt <- dt[!is.na(get("{uc}")) & !is.na(get("{lc}"))]\n'
            f'dt_out <- dt[, .(distinct_users = uniqueN(get("{uc}"))), by = "{lc}"]\n'
            f'dt_out <- dt_out[distinct_users > 1]\nsetorder(dt_out, -distinct_users)\nprint(head(dt_out, 50))'
        )
        expl = f"data.table scaffold for {_PROFILE_NETWORK.label}: `{lc}` concentration."
    else:
        snippet = "print(summary(dt))\nprint(head(dt, 25))"
        expl = f"data.table scaffold for {_PROFILE_GENERIC.label}: summary + head."

    code = (
        f"# Intent: {doc}\n# Profile: {profile.label}\n# Columns:\n{col_comment_r}\n\n"
        f'library(data.table)\npath <- Sys.getenv("FRAUD_DATASET_PATH", unset = "workspace/datasets/sample.csv")\n'
        f"dt <- fread(path)\n{snippet}\n"
        f'# png(file.path(Sys.getenv("FRAUD_PLOT_DIR"), "plot.png")); plot(1); dev.off()\n'
    )
    return code, expl


def generate_scaffold(
    language: Literal["python", "r"],
    intent: str,
    columns: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    cols = columns or _default_columns()
    profile = _intent_profile(intent)
    if language == "python":
        return _build_python(profile, intent, cols)
    return _build_r(profile, intent, cols)
