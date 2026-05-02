"""Fraud rings & collusion: linkage graph + payment cycles + Louvain communities (Polars + NetworkX)."""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import polars as pl

from backend.tools.ring_profiler import enrich_ring_roles
from backend.tools.specialized.fraud_ring import (
    build_payment_digraph,
    infer_payment_columns,
    payment_edges_from_dataframe,
    _cycles_with_limits,
)

_ACCOUNT_CANDS = (
    "account_id",
    "user_id",
    "customer_id",
    "userid",
    "acct_id",
    "member_id",
    "id",
)
_DEVICE_CANDS = (
    "device_id",
    "device_fingerprint",
    "hardware_id",
    "fingerprint",
    "mac_address",
    "device_hash",
)
_ADDRESS_CANDS = (
    "address",
    "street_address",
    "shipping_address",
    "billing_address",
    "normalized_address",
    "postal_address",
)
_PHONE_CANDS = ("phone", "msisdn", "mobile", "phone_number", "tel", "telephone")
_EMPLOYEE_CANDS = ("employee_id", "internal_user_id", "agent_id", "staff_id", "rep_id")
_AMOUNT_CANDS = ("amount", "usd_amount", "total", "value", "txn_amount", "payment_amount")


def _norm_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _pick_col(df: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    by_lower = {_norm_header(c): c for c in df.columns}
    for cand in candidates:
        if cand in df.columns:
            return cand
        n = _norm_header(cand)
        if n in by_lower:
            return by_lower[n]
    return None


def _stable_aux_id(prefix: str, value: str) -> str:
    h = hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()[:14]
    return f"{prefix}:{h}"


def _merge_kinds(ug: nx.Graph, u: str, v: str, kind: str) -> None:
    if ug.has_edge(u, v):
        k = ug[u][v].get("kinds")
        if not isinstance(k, set):
            k = {k} if k else set()
        k.add(kind)
        ug[u][v]["kinds"] = k
    else:
        ug.add_edge(u, v, kinds={kind})


def _add_group_clique(ug: nx.Graph, accounts: list[str], edge_kind: str, *, max_group: int = 100) -> None:
    accs = sorted({a for a in accounts if a and str(a).strip()})
    if len(accs) < 2:
        return
    if len(accs) > max_group:
        accs = accs[:max_group]
    for i, a in enumerate(accs):
        for b in accs[i + 1 :]:
            _merge_kinds(ug, a, b, edge_kind)


def _analyze_ring_graph_from_polars(
    df: pl.DataFrame,
    *,
    account_column: str | None = None,
    payer_column: str | None = None,
    payee_column: str | None = None,
    amount_column: str | None = None,
    min_cycle_len: int = 2,
    max_cycle_len: int = 12,
    max_cycles: int = 500,
    min_employee_pair_n: int = 3,
    internal_amount_threshold: float = 5_000.0,
    louvain_seed: int = 42,
) -> dict[str, Any]:
    """Build undirected linkage graph, directed payment graph, cycles, Louvain, roles."""
    acct_col = account_column and account_column.strip()
    acct_col = acct_col if acct_col and acct_col in df.columns else _pick_col(df, _ACCOUNT_CANDS)
    dev_col = _pick_col(df, _DEVICE_CANDS)
    addr_col = _pick_col(df, _ADDRESS_CANDS)
    phone_col = _pick_col(df, _PHONE_CANDS)
    emp_col = _pick_col(df, _EMPLOYEE_CANDS)
    amt_col = amount_column and amount_column.strip()
    amt_col = amt_col if amt_col and amt_col in df.columns else _pick_col(df, _AMOUNT_CANDS)

    pc, rc = payer_column, payee_column
    if pc and pc not in df.columns:
        pc = None
    if rc and rc not in df.columns:
        rc = None
    if not pc or not rc:
        ipc, irc = infer_payment_columns(df)
        pc = pc or ipc
        rc = rc or irc

    ug = nx.Graph()
    linkage_events: list[dict[str, Any]] = []
    vis_device_spokes: list[tuple[str, str, str]] = []

    if acct_col:
        for col, kind in (
            (dev_col, "shared_device"),
            (addr_col, "shared_address"),
            (phone_col, "shared_phone"),
        ):
            if not col:
                continue
            gdf = df.select(
                pl.col(acct_col).cast(pl.Utf8, strict=False).str.strip_chars().alias("_acct"),
                pl.col(col).cast(pl.Utf8, strict=False).str.strip_chars().alias("_val"),
            ).filter(
                pl.col("_acct").is_not_null()
                & (pl.col("_acct") != "")
                & pl.col("_val").is_not_null()
                & (pl.col("_val") != ""),
            )
            grp = gdf.group_by("_val").agg(pl.col("_acct").unique().alias("members"))
            high = grp.filter(pl.col("members").list.len() >= 2).sort(
                pl.col("members").list.len(), descending=True
            )
            for row in high.head(5_000).iter_rows(named=True):
                members = [str(x) for x in row["members"] if x]
                _add_group_clique(ug, members, kind)
                if col == dev_col and len(members) >= 2:
                    dnode = "device:" + _stable_aux_id("d", str(row["_val"]))
                    cap_m = members[:120]
                    lab = str(row["_val"])[:80]
                    for m in cap_m:
                        vis_device_spokes.append((dnode, m, lab))
                if len(members) >= 10:
                    linkage_events.append(
                        {
                            "pattern": "high_degree_infrastructure",
                            "kind": kind,
                            "shared_value_sample": str(row["_val"])[:80],
                            "accounts_in_group": len(members),
                            "severity": "critical" if len(members) >= 50 else "high",
                        }
                    )

    dgraph = nx.DiGraph()
    pay_stats: dict[str, Any] = {"rows_used": 0, "edges": 0, "cycles_found": 0, "cycles_truncated": False}
    if pc and rc and pc in df.columns and rc in df.columns:
        edge_tbl = payment_edges_from_dataframe(df, pc, rc, amount_col=amt_col if amt_col else None)
        pay_stats["rows_used"] = len(edge_tbl)
        for row in edge_tbl.iter_rows(named=True):
            a, b = str(row["payer"]), str(row["payee"])
            if a == b:
                continue
            _merge_kinds(ug, a, b, "payment")
            ug[a][b]["pay_count"] = ug[a][b].get("pay_count", 0) + int(row.get("transfer_count") or 1)

        dgraph = build_payment_digraph(edge_tbl)
        pay_stats["edges"] = dgraph.number_of_edges()
        cycles, c_trunc = _cycles_with_limits(
            dgraph,
            min_len=min_cycle_len,
            max_len=max_cycle_len,
            max_cycles=max_cycles,
        )
        pay_stats["cycles_truncated"] = bool(c_trunc)
        cycle_nodes: set[str] = set()
        for cyc in cycles:
            cycle_nodes.update(cyc)
        cycle_count = {n: 0 for n in cycle_nodes}
        for cyc in cycles:
            for n in cyc:
                cycle_count[n] = cycle_count.get(n, 0) + 1
    else:
        cycles = []
        c_trunc = False
        cycle_count = {}

    internal_flags: list[dict[str, Any]] = []
    high_value_touch: dict[str, float] = {}
    if emp_col and acct_col and emp_col in df.columns:
        parts: list[pl.Expr] = [
            pl.col(emp_col).cast(pl.Utf8, strict=False).str.strip_chars().alias("_emp"),
            pl.col(acct_col).cast(pl.Utf8, strict=False).str.strip_chars().alias("_acct"),
        ]
        if amt_col and amt_col in df.columns:
            parts.append(pl.col(amt_col).cast(pl.Float64, strict=False).alias("_amt"))
        e_df = df.select(parts).filter(
            pl.col("_emp").is_not_null()
            & (pl.col("_emp") != "")
            & pl.col("_acct").is_not_null()
            & (pl.col("_acct") != "")
            & (pl.col("_emp") != pl.col("_acct")),
        )
        if len(e_df) > 0 and "_amt" in e_df.columns:
            agg = e_df.group_by(["_emp", "_acct"]).agg(
                pl.len().alias("n"),
                pl.col("_amt").sum().alias("total_amt"),
            )
            hot = agg.filter(
                (pl.col("n") >= min_employee_pair_n) | (pl.col("total_amt") >= internal_amount_threshold)
            )
        else:
            agg = e_df.group_by(["_emp", "_acct"]).agg(pl.len().alias("n"))
            hot = agg.filter(pl.col("n") >= min_employee_pair_n)

        for row in hot.iter_rows(named=True):
            e, a = str(row["_emp"]), str(row["_acct"])
            enode_id = "employee:" + _stable_aux_id("emp", e)
            if enode_id not in ug:
                ug.add_node(enode_id, node_type="employee")
            _merge_kinds(ug, enode_id, a, "internal_escalation")
            n = int(row.get("n") or 0)
            ta = float(row.get("total_amt") or 0.0) if "total_amt" in row else 0.0
            internal_flags.append(
                {
                    "employee_id": e,
                    "account_id": a,
                    "touch_count": n,
                    "total_amount": ta,
                    "severity": "high" if ta >= internal_amount_threshold or n >= min_employee_pair_n * 3 else "medium",
                }
            )
            high_value_touch[a] = high_value_touch.get(a, 0.0) + float(ta or n)

    account_nodes = {
        str(n)
        for n in ug.nodes()
        if not str(n).startswith("employee:") and not str(n).startswith("device:")
    }
    sub = ug.subgraph(account_nodes).copy() if account_nodes else nx.Graph()

    communities: list[dict[str, Any]] = []
    community_by_node: dict[str, int] = {}
    if sub.number_of_nodes() > 0:
        try:
            part = nx.community.louvain_communities(sub, seed=louvain_seed, weight=None)
            for i, block in enumerate(part):
                communities.append({"id": i, "members": sorted(block), "size": len(block)})
                for n in block:
                    community_by_node[str(n)] = i
        except Exception:  # noqa: BLE001
            communities = [{"id": 0, "members": sorted(sub.nodes()), "size": sub.number_of_nodes()}]
            for n in sub.nodes():
                community_by_node[str(n)] = 0

    neighbor_communities_count: dict[str, int] = {}
    for n in account_nodes:
        ns = [x for x in ug.neighbors(n) if str(x) in community_by_node]
        comms = {community_by_node[str(x)] for x in ns}
        neighbor_communities_count[str(n)] = len(comms)

    degree_by_account = {str(n): int(ug.degree[n]) for n in account_nodes if n in ug}

    account_list = sorted(account_nodes, key=lambda x: str(x))
    roles = enrich_ring_roles(
        account_ids=account_list,
        degree_by_account=degree_by_account,
        community_by_account=community_by_node,
        cycle_count_by_account={k: cycle_count.get(k, 0) for k in account_list},
        neighbor_communities_count=neighbor_communities_count,
        high_value_touch=high_value_touch,
    )

    risk_communities: set[int] = set()
    for comm in communities:
        cid = comm["id"]
        mem = comm["members"]
        if len(mem) >= 8:
            risk_communities.add(cid)
        max_deg = max((degree_by_account.get(str(m), 0) for m in mem), default=0)
        if max_deg >= 12:
            risk_communities.add(cid)

    pay_stats["cycles_found"] = len(cycles)

    columns_used = {
        "account": acct_col,
        "device": dev_col,
        "address": addr_col,
        "phone": phone_col,
        "employee": emp_col,
        "payer": pc,
        "payee": rc,
        "amount": amt_col,
    }

    return {
        "ug": ug,
        "vis_device_spokes": vis_device_spokes,
        "linkage_events": linkage_events,
        "communities": communities,
        "community_by_node": community_by_node,
        "roles": roles,
        "risk_communities": risk_communities,
        "account_nodes": account_nodes,
        "sub": sub,
        "cycles": cycles,
        "cycles_truncated": c_trunc,
        "cycle_count": cycle_count,
        "pay_stats": pay_stats,
        "internal_flags": internal_flags,
        "degree_by_account": degree_by_account,
        "account_list": account_list,
        "columns_used": columns_used,
        "dgraph": dgraph,
    }


def _gephi_attr_value(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, set):
        return ",".join(sorted(str(x) for x in v))
    return str(v)


def build_gephi_export_graph(
    ug: nx.Graph,
    vis_device_spokes: list[tuple[str, str, str]],
    community_by_node: dict[str, int],
    roles: dict[str, dict[str, Any]],
) -> nx.Graph:
    """Full graph for Gephi/Cytoscape: sanitized attrs + explicit device star edges."""
    H = nx.Graph()
    for n, data in ug.nodes(data=True):
        sid = str(n)
        meta = roles.get(sid, {})
        attrs: dict[str, Any] = {"label": sid, "ring_role": meta.get("role", "")}
        cid = community_by_node.get(sid)
        attrs["community"] = int(cid) if cid is not None else -1
        if sid.startswith("employee:"):
            attrs["node_class"] = "employee"
        elif sid.startswith("device:"):
            attrs["node_class"] = "device"
        else:
            attrs["node_class"] = "account"
        for k, v in data.items():
            if k == "node_type":
                continue
            attrs[f"raw_{k}"] = _gephi_attr_value(v)
        H.add_node(sid, **attrs)

    for u, v, ed in ug.edges(data=True):
        ea: dict[str, Any] = {}
        for k, val in ed.items():
            if k == "kinds" and isinstance(val, set):
                ea["edge_kinds"] = ",".join(sorted(val))
            else:
                ea[k] = _gephi_attr_value(val)
        H.add_edge(str(u), str(v), **ea)

    seen: set[tuple[str, str]] = set()
    for dnode, acct, lab in vis_device_spokes:
        dnode = str(dnode)
        acct = str(acct)
        if not H.has_node(dnode):
            H.add_node(
                dnode,
                label=dnode,
                node_class="device",
                ring_role="",
                community=-1,
                device_label=str(lab)[:300],
            )
        else:
            H.nodes[dnode].setdefault("device_label", str(lab)[:300])
        key = (dnode, acct)
        if key in seen:
            continue
        seen.add(key)
        if H.has_edge(dnode, acct):
            e = H[dnode][acct].get("edge_kinds", "")
            extra = "shared_device_link"
            H[dnode][acct]["edge_kinds"] = f"{e},{extra}" if e else extra
        else:
            H.add_edge(dnode, acct, edge_kinds="shared_device_link", weight=1.0)

    return H


def export_fraud_ring_network(
    dataset_path: str | Path,
    export_format: Literal["gexf", "graphml"],
    *,
    account_column: str | None = None,
    payer_column: str | None = None,
    payee_column: str | None = None,
    amount_column: str | None = None,
    max_rows: int | None = 2_000_000,
    min_cycle_len: int = 2,
    max_cycle_len: int = 12,
    max_cycles: int = 500,
    min_employee_pair_n: int = 3,
    internal_amount_threshold: float = 5_000.0,
    louvain_seed: int = 42,
) -> tuple[bytes, str]:
    """
    Build the same collusion graph as find_fraud_rings and serialize to GEXF or GraphML.

    Returns (file_bytes, filename_suffix_without_dot).
    """
    path = Path(dataset_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    read_kw: dict[str, Any] = {"try_parse_dates": True}
    if max_rows is not None:
        read_kw["n_rows"] = max_rows
    df = pl.read_csv(path, **read_kw)
    if len(df) == 0:
        raise ValueError("Dataset is empty.")

    core = _analyze_ring_graph_from_polars(
        df,
        account_column=account_column,
        payer_column=payer_column,
        payee_column=payee_column,
        amount_column=amount_column,
        min_cycle_len=min_cycle_len,
        max_cycle_len=max_cycle_len,
        max_cycles=max_cycles,
        min_employee_pair_n=min_employee_pair_n,
        internal_amount_threshold=internal_amount_threshold,
        louvain_seed=louvain_seed,
    )
    H = build_gephi_export_graph(
        core["ug"],
        core["vis_device_spokes"],
        core["community_by_node"],
        core["roles"],
    )
    buf = io.BytesIO()
    fmt = export_format.lower().strip()
    if fmt == "gexf":
        nx.write_gexf(H, buf, encoding="utf-8")
        return buf.getvalue(), "gexf"
    if fmt == "graphml":
        nx.write_graphml(H, buf, encoding="utf-8")
        return buf.getvalue(), "graphml"
    raise ValueError(f"Unsupported export format: {export_format!r}")


def _multi_hop_structural_summary(ug: nx.Graph) -> dict[str, Any]:
    """Lightweight graph hints for Account→shared device→peer Account style narratives (≥3-hop reasoning)."""
    bridges = 0
    for n in ug.nodes():
        if not str(n).startswith("device:"):
            continue
        acc_neighbors = [
            u for u in ug.neighbors(n) if not str(u).startswith(("device:", "employee:"))
        ]
        if len(acc_neighbors) >= 2:
            bridges += 1
    account_nodes = sum(1 for n in ug.nodes() if not str(n).startswith(("device:", "employee:")))
    max_deg = max((int(ug.degree[n]) for n in ug.nodes()), default=0)
    return {
        "shared_device_multi_account_bridges": bridges,
        "account_nodes": account_nodes,
        "max_degree": max_deg,
        "three_hop_narrative_ready": bool(bridges > 0 or max_deg >= 3),
        "interpretation": (
            "Shared-device bridges connect 2+ accounts through one device. "
            "Combine with payer→payee or address/phone edges to argue Account→shared attribute→Account→device paths."
        ),
    }


def find_fraud_rings(
    dataset_path: str | Path,
    *,
    account_column: str | None = None,
    payer_column: str | None = None,
    payee_column: str | None = None,
    amount_column: str | None = None,
    max_rows: int | None = 2_000_000,
    min_cycle_len: int = 2,
    max_cycle_len: int = 12,
    max_cycles: int = 500,
    min_employee_pair_n: int = 3,
    internal_amount_threshold: float = 5_000.0,
    max_graph_nodes: int = 900,
    max_graph_edges: int = 3_500,
    louvain_seed: int = 42,
) -> dict[str, Any]:
    """
    Build a unified account linkage graph, detect payment cycles, run Louvain communities,
    surface internal↔account hot edges, and emit a force-graph payload.
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

    core = _analyze_ring_graph_from_polars(
        df,
        account_column=account_column,
        payer_column=payer_column,
        payee_column=payee_column,
        amount_column=amount_column,
        min_cycle_len=min_cycle_len,
        max_cycle_len=max_cycle_len,
        max_cycles=max_cycles,
        min_employee_pair_n=min_employee_pair_n,
        internal_amount_threshold=internal_amount_threshold,
        louvain_seed=louvain_seed,
    )

    ug = core["ug"]
    vis_device_spokes = core["vis_device_spokes"]
    linkage_events = core["linkage_events"]
    communities = core["communities"]
    community_by_node = core["community_by_node"]
    roles = core["roles"]
    risk_communities = core["risk_communities"]
    account_nodes = core["account_nodes"]
    sub = core["sub"]
    cycles = core["cycles"]
    c_trunc = core["cycles_truncated"]
    pay_stats = core["pay_stats"]
    internal_flags = core["internal_flags"]
    columns_used = core["columns_used"]
    multi_hop_scan = _multi_hop_structural_summary(ug)

    vis_nodes: list[dict[str, Any]] = []
    vis_links: list[dict[str, Any]] = []
    trim_note: str | None = None

    if ug.number_of_nodes() > 0:
        nodes_all = list(ug.nodes())
        if len(nodes_all) > max_graph_nodes:
            aux = [
                n
                for n in nodes_all
                if str(n).startswith("employee:") or str(n).startswith("device:")
            ]
            acct_sorted = sorted(
                [n for n in nodes_all if n not in aux],
                key=lambda x: int(ug.degree[x]) if x in ug else 0,
                reverse=True,
            )
            keep = set(acct_sorted[: max_graph_nodes - len(aux)] + aux)
            ug_vis = ug.subgraph(keep).copy()
            trim_note = f"Graph trimmed to {max_graph_nodes} nodes for UI performance."
        else:
            ug_vis = ug
            keep = set(ug_vis.nodes())

        for n in ug_vis.nodes():
            sid = str(n)
            nt = ug_vis.nodes[n].get("node_type", "account")
            if sid.startswith("employee:"):
                nt = "employee"
            elif sid.startswith("device:"):
                nt = "device"
            comm = community_by_node.get(sid)
            role_info = roles.get(sid, {})
            glow = bool(comm is not None and comm in risk_communities) or role_info.get("role") == "hub"
            vis_nodes.append(
                {
                    "id": sid,
                    "type": nt,
                    "community_id": comm,
                    "role": role_info.get("role", "peripheral"),
                    "degree": int(ug.degree[n]) if n in ug else 0,
                    "glow": glow,
                    "label": sid if len(sid) < 32 else sid[:14] + "…",
                }
            )

        edge_seen = 0
        for u, v, data in ug_vis.edges(data=True):
            kinds = data.get("kinds") or set()
            if not isinstance(kinds, set):
                kinds = {kinds}
            if kinds == {"shared_device"}:
                continue
            kind_pick = sorted(kinds)[0] if kinds else "linkage"
            solid = "payment" in kinds
            dashed = (
                bool(kinds & {"shared_address", "shared_phone", "internal_escalation"})
                or "internal" in kind_pick
            )
            internal = bool(kinds & {"internal_escalation"}) or ("internal" in kind_pick)
            vis_links.append(
                {
                    "source": str(u),
                    "target": str(v),
                    "kind": kind_pick,
                    "lineDash": not solid,
                    "color": "rgba(248,113,113,0.65)" if internal else ("rgba(96,165,250,0.45)" if dashed else "rgba(148,163,184,0.55)"),
                }
            )
            edge_seen += 1
            if edge_seen >= max_graph_edges:
                trim_note = (trim_note or "") + f" Edge list capped at {max_graph_edges}."
                break

        keep_str = {str(x) for x in keep}
        dev_nodes_added: set[str] = set()
        for dnode, acct, lab in vis_device_spokes:
            if acct not in keep_str:
                continue
            if dnode not in dev_nodes_added:
                dev_nodes_added.add(dnode)
                glow_d = community_by_node.get(acct) is not None and community_by_node[acct] in risk_communities
                vis_nodes.append(
                    {
                        "id": dnode,
                        "type": "device",
                        "community_id": None,
                        "role": "peripheral",
                        "degree": 0,
                        "glow": glow_d,
                        "label": lab[:18] + ("…" if len(lab) > 18 else ""),
                        "device_label": lab,
                    }
                )
            vis_links.append(
                {
                    "source": dnode,
                    "target": acct,
                    "kind": "shared_device",
                    "lineDash": True,
                    "color": "rgba(167,139,250,0.55)",
                }
            )
            edge_seen += 1
            if edge_seen >= max_graph_edges:
                trim_note = (trim_note or "") + " Device edges truncated."
                break

    return {
        "ok": True,
        "rows_read": len(df),
        "columns_used": columns_used,
        "graph_summary": {
            "nodes": ug.number_of_nodes(),
            "edges": ug.number_of_edges(),
            "account_nodes": len(account_nodes),
            "density": round(nx.density(sub), 8) if sub.number_of_nodes() > 1 else 0.0,
        },
        "communities": communities[:200],
        "community_count": len(communities),
        "cycles": [
            {"path": " → ".join(c + [c[0]]), "length": len(c), "nodes": c}
            for c in cycles[: min(100, len(cycles))]
        ],
        "cycles_found": len(cycles),
        "cycles_truncated": c_trunc,
        "payment_summary": pay_stats,
        "linkage_alerts": linkage_events[:100],
        "internal_external_flags": internal_flags[:200],
        "node_roles": roles,
        "graph_data": {"nodes": vis_nodes, "links": vis_links},
        "visualization_note": trim_note,
        "high_risk_community_ids": sorted(risk_communities),
        "multi_hop_scan": multi_hop_scan,
    }
