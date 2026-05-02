"""Invokes compiled LangGraph."""
from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from backend.agents.registry import get_fraud_agent
from backend.agent.coordinator import resolve_persona_id
from backend.config import settings
from backend.schemas import ChatMessage

from .graph import get_compiled_graph, invalidate_compiled_graph_cache
from .tool_self_heal import strip_traceback_for_agent_ui
from .tools_langchain import set_agent_context

_TOOL_LINE_RE = re.compile(r"^\[tool\s+([^\]]+)\]\s*([\s\S]*)$", re.I)


def _to_lc(messages: list[ChatMessage]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
        else:
            out.append(SystemMessage(content=m.content))
    return out


def _from_lc(messages: list[BaseMessage]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append(ChatMessage(role="user", content=str(m.content)))
        elif isinstance(m, AIMessage):
            out.append(ChatMessage(role="assistant", content=str(m.content)))
        elif isinstance(m, SystemMessage):
            out.append(ChatMessage(role="system", content=str(m.content)))
        elif isinstance(m, ToolMessage):
            safe = strip_traceback_for_agent_ui(str(m.content))
            out.append(ChatMessage(role="assistant", content=f"[tool {m.name}] {safe}"))
        elif hasattr(m, "content"):
            out.append(ChatMessage(role="assistant", content=str(m.content)))
    return out


def _infer_confidence_from_tool_payload(data: dict, tool_name: str) -> float:
    if isinstance(data.get("confidence_score"), (int, float)):
        return max(0.0, min(1.0, float(data["confidence_score"])))
    if tool_name == "analyze_chargeback_risk_tool":
        wp = data.get("win_probability")
        if isinstance(wp, (int, float)):
            return max(0.0, min(1.0, float(wp)))
        wpp = data.get("win_probability_percent")
        if isinstance(wpp, (int, float)):
            return max(0.0, min(1.0, float(wpp) / 100.0))
        scr = data.get("chargeback_risk_score")
        if isinstance(scr, (int, float)):
            return max(0.0, min(1.0, float(scr) / 100.0))
    if tool_name == "analyze_ato_risk_tool":
        safety = data.get("safety_score")
        risk = data.get("ato_risk_score")
        if isinstance(safety, (int, float)):
            return max(0.0, min(1.0, float(safety) / 100.0))
        if isinstance(risk, (int, float)):
            return max(0.0, min(1.0, 1.0 - float(risk) / 100.0))
    if tool_name == "detect_bot_clusters_tool":
        bd = data.get("bot_density_pct")
        if isinstance(bd, (int, float)):
            return max(0.0, min(1.0, 0.42 + float(bd) / 180.0))
    if tool_name == "find_fraud_rings_tool":
        gs = data.get("graph_summary")
        if isinstance(gs, dict):
            edges = gs.get("edges")
            if isinstance(edges, int) and edges > 0:
                return max(0.0, min(1.0, 0.52 + min(edges, 80) * 0.005))
        mh = data.get("multi_hop_scan")
        if isinstance(mh, dict) and mh.get("three_hop_narrative_ready"):
            return 0.68
    if tool_name == "build_user_behavioral_profile_tool" and data.get("ok") is True:
        n = data.get("historical_event_count")
        if isinstance(n, int) and n >= 5:
            return 0.78
        if isinstance(n, int) and n > 0:
            return 0.62
    if tool_name == "chargeback_trust_velocity_tool":
        if data.get("seasoning_assessment"):
            return 0.88
        rs = data.get("risk_score")
        if isinstance(rs, (int, float)):
            return max(0.0, min(1.0, float(rs) / 100.0))
        return 0.72
    if tool_name == "search_historical_overlap_tool":
        if data.get("recidivist_fraudster"):
            return 0.9
        oc = data.get("other_case_count_excluding_active")
        if isinstance(oc, int) and oc > 0:
            return max(0.0, min(1.0, 0.55 + min(6, oc) * 0.05))
        return 0.56
    if tool_name == "humanoid_stress_test_linkage_tool" and data.get("global_hits"):
        return 0.84
    if tool_name == "humanoid_stress_test_linkage_tool":
        return 0.58
    return 0.72


def _enrich_tool_line(content: str, agent_type: str) -> str:
    m = _TOOL_LINE_RE.match(content.strip())
    if not m:
        return content
    name, body = m.group(1).strip(), m.group(2).strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return content
    if not isinstance(data, dict):
        return content
    if "agent_type" not in data:
        data["agent_type"] = agent_type
    if "confidence_score" not in data:
        data["confidence_score"] = _infer_confidence_from_tool_payload(data, name)
    return f"[tool {name}] {json.dumps(data, default=str)}"


def _min_confidence_in_last_turn(msgs: list[ChatMessage]) -> tuple[float | None, str | None]:
    """Minimum inferred confidence among tool payloads after the last user message."""
    block: list[ChatMessage] = []
    for m in reversed(msgs):
        if m.role == "user":
            break
        if m.role == "assistant":
            block.append(m)
    best_name: str | None = None
    min_c: float | None = None
    for m in block:
        mm = _TOOL_LINE_RE.match(m.content.strip())
        if not mm:
            continue
        name, body = mm.group(1).strip(), mm.group(2).strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        c = data.get("confidence_score")
        if not isinstance(c, (int, float)):
            c = _infer_confidence_from_tool_payload(data, name)
        c = float(c)
        if min_c is None or c < min_c:
            min_c = c
            best_name = name
    return min_c, best_name


def _apply_agent_enrichment_and_rfi(msgs: list[ChatMessage], persona_id: str) -> list[ChatMessage]:
    fa = get_fraud_agent(persona_id)
    at = fa.agent_type
    thr = float(fa.confidence_threshold)
    out: list[ChatMessage] = []
    for m in msgs:
        if m.role == "assistant":
            out.append(ChatMessage(role="assistant", content=_enrich_tool_line(m.content, at)))
        else:
            out.append(m)
    min_c, tool_name = _min_confidence_in_last_turn(out)
    if min_c is not None and min_c < thr:
        out.append(
            ChatMessage(
                role="assistant",
                content="[RFI]"
                + json.dumps(
                    {
                        "kind": "lead_investigator_rfi",
                        "confidence_score": min_c,
                        "threshold": thr,
                        "after_tool": tool_name,
                        "prompt": (
                            "Lead Investigator: evidence is insufficient for a decisive automated verdict. "
                            "Provide additional columns, user_id, time window, or authoritative labels."
                        ),
                    },
                    default=str,
                ),
            )
        )
    return out


def invoke_chat(
    messages: list[ChatMessage],
    *,
    case_id: str | None,
    dataset_path: str | None,
    duckdb_path: str | None = None,
    persona_id: str | None = None,
    thread_reset: bool = False,
) -> tuple[list[ChatMessage], dict | None]:
    set_agent_context(case_id=case_id, dataset_path=dataset_path, duckdb_path=duckdb_path)
    pid = resolve_persona_id(persona_id)
    if thread_reset:
        invalidate_compiled_graph_cache(pid)
    graph = get_compiled_graph(pid)
    state = graph.invoke({"messages": _to_lc(messages), "next_agent": "analyst"})
    raw_msgs = _from_lc(state["messages"])
    enriched = _apply_agent_enrichment_and_rfi(raw_msgs, pid)
    debug = None
    if settings.debug_agent:
        debug = {"next_agent": state.get("next_agent"), "persona_id": pid, "thread_reset": thread_reset}
    return enriched, debug
