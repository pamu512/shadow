"""Fraud Ring Detective — payment graphs and circular path detection (Polars + NetworkX)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import networkx as nx
import polars as pl

# Normalized substrings that suggest payer / payee columns (lowercase, alphanumeric-only names).
_PAYER_HINTS: frozenset[str] = frozenset(
    {
        "payer",
        "sender",
        "from",
        "source",
        "debtor",
        "buyer",
        "origin",
        "remitter",
        "payerid",
        "senderid",
        "fromaccount",
        "sourceaccount",
        "origaccount",
        "buyerid",
        "customerid",
        "user",
        "account",
    }
)
_PAYEE_HINTS: frozenset[str] = frozenset(
    {
        "payee",
        "receiver",
        "recipient",
        "to",
        "dest",
        "beneficiary",
        "creditor",
        "seller",
        "target",
        "payeeid",
        "receiverid",
        "toaccount",
        "beneficiaryaccount",
        "sellerid",
        "counterparty",
        "merchant",
    }
)


def _normalize_col_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _score_against_hints(norm: str, hints: frozenset[str]) -> int:
    if not norm:
        return 0
    return sum(1 for h in hints if h in norm)


def infer_payment_columns(df: pl.DataFrame) -> tuple[str | None, str | None]:
    """Pick likely payer / payee columns from headers using fuzzy keyword hints."""
    best_payer: tuple[int, str] = (0, "")
    best_payee: tuple[int, str] = (0, "")
    for col in df.columns:
        norm = _normalize_col_name(col)
        ps = _score_against_hints(norm, _PAYER_HINTS)
        ys = _score_against_hints(norm, _PAYEE_HINTS)
        if ps > best_payer[0]:
            best_payer = (ps, col)
        if ys > best_payee[0]:
            best_payee = (ys, col)
    payer = best_payer[1] if best_payer[0] > 0 else None
    payee = best_payee[1] if best_payee[0] > 0 else None

    if payer is not None and payer == payee:
        # Same column won both — pick second-best payee
        alt = sorted(
            (( _score_against_hints(_normalize_col_name(c), _PAYEE_HINTS), c) for c in df.columns if c != payer),
            reverse=True,
        )
        payee = alt[0][1] if alt and alt[0][0] > 0 else None

    return payer, payee


def payment_edges_from_dataframe(
    df: pl.DataFrame,
    payer_col: str,
    payee_col: str,
    *,
    amount_col: str | None = None,
) -> pl.DataFrame:
    """
    Collapse parallel transfers into one row per (payer, payee).

    Columns: payer, payee, transfer_count, and optionally total_amount.
    """
    base = df.select(
        pl.col(payer_col).cast(pl.Utf8).str.strip_chars().alias("payer"),
        pl.col(payee_col).cast(pl.Utf8).str.strip_chars().alias("payee"),
    ).filter(pl.col("payer").is_not_null() & pl.col("payee").is_not_null())
    base = base.filter((pl.col("payer") != "") & (pl.col("payee") != ""))

    if amount_col and amount_col in df.columns:
        with_amt = df.select(
            pl.col(payer_col).cast(pl.Utf8).str.strip_chars().alias("payer"),
            pl.col(payee_col).cast(pl.Utf8).str.strip_chars().alias("payee"),
            pl.col(amount_col).cast(pl.Float64, strict=False).alias("_amt"),
        )
        with_amt = with_amt.filter(
            pl.col("payer").is_not_null()
            & pl.col("payee").is_not_null()
            & (pl.col("payer") != "")
            & (pl.col("payee") != "")
        )
        return (
            with_amt.group_by(["payer", "payee"])
            .agg(
                pl.len().alias("transfer_count"),
                pl.col("_amt").sum().alias("total_amount"),
            )
            .sort(["transfer_count", "payer", "payee"], descending=[True, False, False])
        )

    return (
        base.group_by(["payer", "payee"])
        .agg(pl.len().alias("transfer_count"))
        .sort(["transfer_count", "payer", "payee"], descending=[True, False, False])
    )


def build_payment_digraph(edge_table: pl.DataFrame) -> nx.DiGraph:
    """Build a directed graph: payer -> payee with edge attributes from Polars rows."""
    g = nx.DiGraph()
    rows = edge_table.to_dicts()
    for row in rows:
        p, y = str(row["payer"]), str(row["payee"])
        data: dict[str, Any] = {"transfer_count": int(row.get("transfer_count") or 0)}
        if "total_amount" in row and row["total_amount"] is not None:
            data["total_amount"] = float(row["total_amount"])
        if g.has_edge(p, y):
            g[p][y]["transfer_count"] += data["transfer_count"]
            if "total_amount" in data:
                g[p][y]["total_amount"] = g[p][y].get("total_amount", 0.0) + data["total_amount"]
        else:
            g.add_edge(p, y, **data)
    return g


def _cycles_with_limits(
    g: nx.DiGraph,
    *,
    min_len: int,
    max_len: int,
    max_cycles: int,
) -> tuple[list[list[str]], bool]:
    """Enumerate simple directed cycles with caps; returns (cycles, truncated)."""
    out: list[list[str]] = []
    truncated = False
    for cycle in nx.simple_cycles(g):
        if len(cycle) < min_len or len(cycle) > max_len:
            continue
        out.append([str(n) for n in cycle])
        if len(out) >= max_cycles:
            truncated = True
            break
    return out, truncated


def _cycles_to_polars(cycles: list[list[str]]) -> pl.DataFrame:
    if not cycles:
        return pl.DataFrame(
            {
                "cycle_id": pl.Series([], dtype=pl.UInt32),
                "cycle_length": pl.Series([], dtype=pl.UInt32),
                "path": pl.Series([], dtype=pl.Utf8),
            }
        )
    paths = [" → ".join(c + [c[0]]) for c in cycles]
    return pl.DataFrame(
        {
            "cycle_id": pl.Series(range(1, len(cycles) + 1), dtype=pl.UInt32),
            "cycle_length": pl.Series([len(c) for c in cycles], dtype=pl.UInt32),
            "path": pl.Series(paths, dtype=pl.Utf8),
        }
    )


def find_circular_payment_paths(
    dataset_path: str | Path,
    *,
    payer_col: str | None = None,
    payee_col: str | None = None,
    amount_col: str | None = None,
    max_rows: int | None = 2_000_000,
    min_cycle_len: int = 2,
    max_cycle_len: int = 16,
    max_cycles: int = 1_000,
) -> dict[str, Any]:
    """
    Load a transaction CSV with Polars, build a payer→payee DiGraph in NetworkX, and report
    elementary circular payment paths (each party on the cycle is distinct; closing edge implied).

    Parameters
    ----------
    dataset_path:
        Path to CSV (same style as case datasets: header row).
    payer_col / payee_col:
        Explicit columns; if omitted, columns are inferred from headers.
    amount_col:
        Optional numeric column aggregated as ``total_amount`` on collapsed edges.
    max_rows:
        Optional cap on rows read (large files). ``None`` = read full file.
    min_cycle_len:
        Minimum distinct nodes in a cycle (``2`` ⇒ A→B→A). Use ``1`` to include self-loops.
    max_cycle_len / max_cycles:
        Guardrails — cycle enumeration can grow quickly on dense graphs.

    Returns
    -------
    JSON-friendly dict with summary stats, inferred columns, up to ``max_cycles`` cycles,
    and a small Polars preview serialized as rows.
    """
    path = Path(dataset_path)
    if not path.is_file():
        return {"ok": False, "error": f"Dataset not found: {path}"}

    read_kwargs: dict[str, Any] = {"try_parse_dates": True}
    if max_rows is not None:
        read_kwargs["n_rows"] = max_rows

    try:
        df = pl.read_csv(path, **read_kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Failed to read CSV: {exc}"}

    if len(df) == 0:
        return {"ok": False, "error": "Dataset is empty."}

    inferred = False
    pc, rc = payer_col, payee_col
    if not pc or not rc:
        ipc, irc = infer_payment_columns(df)
        pc = pc or ipc
        rc = rc or irc
        inferred = pc is not None and rc is not None and (payer_col is None or payee_col is None)
    if not pc or not rc or pc not in df.columns or rc not in df.columns:
        return {
            "ok": False,
            "error": "Could not resolve payer and payee columns.",
            "columns": list(df.columns),
            "hint": "Pass payer_col and payee_col explicitly.",
        }

    if amount_col and amount_col not in df.columns:
        return {"ok": False, "error": f"amount_col {amount_col!r} not in dataset."}

    edge_tbl = payment_edges_from_dataframe(df, pc, rc, amount_col=amount_col)
    graph = build_payment_digraph(edge_tbl)

    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    if n_nodes == 0:
        return {
            "ok": True,
            "cycles_found": 0,
            "payer_col": pc,
            "payee_col": rc,
            "amount_col": amount_col,
            "columns_inferred": inferred,
            "graph": {"nodes": 0, "edges": 0},
            "cycles": [],
            "note": "No valid payer/payee rows after cleaning.",
        }

    cycles, truncated = _cycles_with_limits(
        graph,
        min_len=min_cycle_len,
        max_len=max_cycle_len,
        max_cycles=max_cycles,
    )
    cyc_df = _cycles_to_polars(cycles)

    preview_limit = min(50, len(cycles))
    preview = cyc_df.head(preview_limit).to_dicts()

    return {
        "ok": True,
        "payer_col": pc,
        "payee_col": rc,
        "amount_col": amount_col,
        "columns_inferred": inferred,
        "graph": {
            "nodes": n_nodes,
            "edges": n_edges,
            "density": round(nx.density(graph), 8),
        },
        "rows_read": len(df),
        "unique_party_pairs": len(edge_tbl),
        "cycles_found": len(cycles),
        "truncated": truncated,
        "limits": {
            "max_cycle_len": max_cycle_len,
            "max_cycles": max_cycles,
            "min_cycle_len": min_cycle_len,
        },
        "cycles_preview": preview,
    }


def find_circular_payment_paths_lazyframe(
    lf: pl.LazyFrame,
    payer_col: str,
    payee_col: str,
    *,
    amount_col: str | None = None,
    min_cycle_len: int = 2,
    max_cycle_len: int = 16,
    max_cycles: int = 1_000,
) -> dict[str, Any]:
    """Same as :func:`find_circular_payment_paths` but from an in-memory LazyFrame (for pipelines)."""
    df = lf.collect()
    edge_tbl = payment_edges_from_dataframe(df, payer_col, payee_col, amount_col=amount_col)
    graph = build_payment_digraph(edge_tbl)
    cycles, truncated = _cycles_with_limits(
        graph,
        min_len=min_cycle_len,
        max_len=max_cycle_len,
        max_cycles=max_cycles,
    )
    cyc_df = _cycles_to_polars(cycles)
    preview = cyc_df.head(min(50, len(cycles))).to_dicts()
    return {
        "ok": True,
        "payer_col": payer_col,
        "payee_col": payee_col,
        "amount_col": amount_col,
        "graph": {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "density": round(nx.density(graph), 8) if graph.number_of_nodes() > 0 else 0.0,
        },
        "unique_party_pairs": len(edge_tbl),
        "cycles_found": len(cycles),
        "truncated": truncated,
        "cycles_preview": preview,
    }


# Back-compat names (older stubs)
def network_analysis_stub() -> str:
    return (
        "Use find_circular_payment_paths(dataset_path, payer_col=..., payee_col=...) "
        "for Polars + NetworkX circular payment detection."
    )


def graph_clustering_stub() -> str:
    return "stub: graph_clustering_louvain — not implemented yet."
