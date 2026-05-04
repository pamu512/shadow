"""Invokes compiled LangGraph."""
from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from backend.agents.registry import get_fraud_agent
from backend.agent.coordinator import resolve_persona_id
from backend.config import settings
from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.database.models import Case
from backend.database.session import SessionLocal
from backend.schemas import ChatMessage
from backend.tools.warehouse_query import clear_warehouse_query_context, set_warehouse_query_context

from .graph import get_compiled_graph, invalidate_compiled_graph_cache
from .ollama import get_llm
from .tool_confidence import infer_tool_confidence_score
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
    """Map LangGraph state to API chat lines. Omit SystemMessage: those are model-only (ReAct prompt + context injection)."""
    out: list[ChatMessage] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append(ChatMessage(role="user", content=str(m.content)))
        elif isinstance(m, AIMessage):
            out.append(ChatMessage(role="assistant", content=str(m.content)))
        elif isinstance(m, SystemMessage):
            continue
        elif isinstance(m, ToolMessage):
            safe = strip_traceback_for_agent_ui(str(m.content))
            out.append(ChatMessage(role="assistant", content=f"[tool {m.name}] {safe}"))
        elif hasattr(m, "content"):
            out.append(ChatMessage(role="assistant", content=str(m.content)))
    return out


def _enrich_tool_line(content: str, agent_type: str, llm) -> str:
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
        data["confidence_score"] = infer_tool_confidence_score(llm, name, data)
    return f"[tool {name}] {json.dumps(data, default=str)}"


def _min_confidence_in_last_turn(msgs: list[ChatMessage], llm) -> tuple[float | None, str | None]:
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
            c = infer_tool_confidence_score(llm, name, data)
        c = float(c)
        if min_c is None or c < min_c:
            min_c = c
            best_name = name
    return min_c, best_name


def _apply_agent_enrichment_and_rfi(msgs: list[ChatMessage], persona_id: str) -> list[ChatMessage]:
    fa = get_fraud_agent(persona_id)
    at = fa.agent_type
    thr = float(fa.confidence_threshold)
    llm = get_llm()
    out: list[ChatMessage] = []
    for m in msgs:
        if m.role == "assistant":
            out.append(ChatMessage(role="assistant", content=_enrich_tool_line(m.content, at, llm)))
        else:
            out.append(m)
    min_c, tool_name = _min_confidence_in_last_turn(out, llm)
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


def _stable_thread_id(case_id: str | None, persona_id: str, client_thread_id: str | None) -> str:
    base = (client_thread_id or "").strip() or uuid.uuid4().hex
    cid = (case_id or "nocase").strip()
    return f"{cid}:{persona_id}:{base}"


def _messages_for_checkpoint_invoke(
    graph,
    config: dict,
    full_lc: list[BaseMessage],
) -> tuple[list[BaseMessage], bool]:
    """Return (messages_input, skip_invoke). Delta vs checkpoint so add_messages does not duplicate."""
    try:
        snap = graph.get_state(config)
        existing = list((snap.values or {}).get("messages") or [])
    except Exception:
        return full_lc, False
    n, m = len(existing), len(full_lc)
    if n == 0:
        return full_lc, False
    if m < n:
        # Client shorter than checkpoint — rotate thread_id client-side; still send full payload once.
        return full_lc, False
    if m > n:
        return full_lc[n:], False
    return [], True


def invoke_chat(
    messages: list[ChatMessage],
    *,
    case_id: str | None,
    dataset_path: str | None,
    duckdb_path: str | None = None,
    persona_id: str | None = None,
    thread_reset: bool = False,
    thread_id: str | None = None,
) -> tuple[list[ChatMessage], dict | None]:
    tid = DEFAULT_TENANT_ID
    if case_id:
        dbs = SessionLocal()
        try:
            row = dbs.query(Case).filter(Case.id == case_id).first()
            if row and getattr(row, "tenant_id", None):
                tid = str(row.tenant_id).strip() or DEFAULT_TENANT_ID
        finally:
            dbs.close()
    set_warehouse_query_context(tenant_id=tid, viewer_case_id=case_id)
    try:
        set_agent_context(case_id=case_id, dataset_path=dataset_path, duckdb_path=duckdb_path)
        pid = resolve_persona_id(persona_id)
        if thread_reset:
            invalidate_compiled_graph_cache(pid)
        graph = get_compiled_graph(pid)
        tid_graph = _stable_thread_id(case_id, pid, thread_id)
        config: dict = {"configurable": {"thread_id": tid_graph}}
        full_lc = _to_lc(messages)
        delta, skip_invoke = _messages_for_checkpoint_invoke(graph, config, full_lc)
        if skip_invoke:
            snap = graph.get_state(config)
            state_msgs = list((snap.values or {}).get("messages") or [])
            raw_msgs = _from_lc(state_msgs)
        else:
            _ = graph.invoke({"messages": delta, "next_agent": "analyst"}, config)
            snap = graph.get_state(config)
            state_msgs = list((snap.values or {}).get("messages") or [])
            raw_msgs = _from_lc(state_msgs)
        enriched = _apply_agent_enrichment_and_rfi(raw_msgs, pid)
        debug = None
        if settings.debug_agent:
            vals = (snap.values or {}) if snap else {}
            debug = {
                "next_agent": vals.get("next_agent"),
                "persona_id": pid,
                "thread_reset": thread_reset,
                "thread_id": tid_graph,
                "checkpoint_skip": skip_invoke,
            }
        return enriched, debug
    finally:
        clear_warehouse_query_context()
