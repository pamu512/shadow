"""Role labels for accounts in a fraud-ring graph (kingpins, mules, bridges)."""
from __future__ import annotations

from typing import Any


def enrich_ring_roles(
    *,
    account_ids: list[str],
    degree_by_account: dict[str, int],
    community_by_account: dict[str, int],
    cycle_count_by_account: dict[str, int],
    neighbor_communities_count: dict[str, int],
    high_value_touch: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """
    Assign investigative roles per account.

    Priority: bridge > hub > mule > peripheral.
    """
    if not account_ids:
        return {}

    degrees = [degree_by_account.get(a, 0) for a in account_ids]
    sorted_d = sorted((d for d in degrees if d > 0), reverse=True)
    hub_thr = 4
    if sorted_d:
        idx = min(len(sorted_d) - 1, max(0, len(sorted_d) // 9))
        hub_thr = max(4, sorted_d[idx])

    out: dict[str, dict[str, Any]] = {}
    for aid in account_ids:
        d = int(degree_by_account.get(aid, 0))
        comm = community_by_account.get(aid)
        cyc = int(cycle_count_by_account.get(aid, 0))
        bridge_n = int(neighbor_communities_count.get(aid, 0))
        hv = float(high_value_touch.get(aid, 0.0))

        reasons: list[str] = []
        role = "peripheral"

        if bridge_n >= 2:
            role = "bridge"
            reasons.append(f"neighbors span {bridge_n} distinct communities")
        elif d >= hub_thr:
            role = "hub"
            reasons.append(f"high degree ({d}) vs cohort")
        if role == "peripheral" and cyc >= 1 and d <= 5:
            role = "mule"
            reasons.append("on circular payment path with limited connectivity")
        elif role == "peripheral" and d <= 2 and hv > 0:
            role = "mule"
            reasons.append("low linkage with concentrated internal/escalation touches")

        if role == "peripheral":
            reasons.append("ring member — review shared infra and flows")

        out[aid] = {
            "role": role,
            "degree": d,
            "community_id": comm,
            "cycles_involved": cyc,
            "neighbor_community_diversity": bridge_n,
            "internal_edge_weight_proxy": round(hv, 4),
            "reasons": reasons,
        }
    return out


def summarize_roles(node_roles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts for agent narratives."""
    buckets: dict[str, list[str]] = {}
    for aid, meta in node_roles.items():
        r = str(meta.get("role", "peripheral"))
        buckets.setdefault(r, []).append(aid)
    for k in buckets:
        buckets[k] = sorted(set(buckets[k]))
    return {
        "counts": {k: len(v) for k, v in buckets.items()},
        "hubs_sample": buckets.get("hub", [])[:12],
        "bridges_sample": buckets.get("bridge", [])[:12],
        "mules_sample": buckets.get("mule", [])[:12],
    }
