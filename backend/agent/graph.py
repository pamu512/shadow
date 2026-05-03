"""Multi-agent LangGraph: supervisor routes to code, ML, or analyst ReAct subgraphs."""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from threading import Lock

from .checkpointing import get_langgraph_checkpointer
from .coordinator import (
    build_analyst_system_prompt,
    build_code_agent_prompt,
    build_ml_agent_prompt,
    build_supervisor_context,
)
from .ollama import get_llm
from .personas import get_persona
from .reasoning_hooks import context_injection_node
from .supervisor_routing import invoke_supervisor_route
from .state import AgentState
from .tools_langchain import build_analyst_tools, build_code_tools, build_ml_tools


def _make_supervisor_node(supervisor_prompt: str):
    def supervisor_node(state: AgentState) -> dict:
        llm = get_llm()
        messages = state["messages"]
        last_user = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                last_user = str(m.content)
                break
        nxt = invoke_supervisor_route(llm, supervisor_prompt=supervisor_prompt, last_user=last_user)
        return {"next_agent": nxt}

    return supervisor_node


def route_from_supervisor(state: AgentState) -> Literal["code_agent", "ml_agent", "analyst"]:
    return state.get("next_agent") or "analyst"


def build_graph(persona_id: str):
    """Compile the LangGraph for a specific investigative persona (cached per id)."""
    persona = get_persona(persona_id)
    llm = get_llm()
    code_agent = create_react_agent(llm, build_code_tools(), prompt=build_code_agent_prompt(persona))
    ml_agent = create_react_agent(llm, build_ml_tools(), prompt=build_ml_agent_prompt(persona))
    analyst_agent = create_react_agent(
        llm,
        build_analyst_tools(persona.id),
        prompt=build_analyst_system_prompt(persona),
    )
    supervisor_node = _make_supervisor_node(build_supervisor_context(persona))

    def run_code(state: AgentState) -> dict:
        prev_n = len(state["messages"])
        out = code_agent.invoke({"messages": state["messages"]})
        new_msgs = out["messages"][prev_n:]
        return {"messages": new_msgs}

    def run_ml(state: AgentState) -> dict:
        prev_n = len(state["messages"])
        out = ml_agent.invoke({"messages": state["messages"]})
        new_msgs = out["messages"][prev_n:]
        return {"messages": new_msgs}

    def run_analyst(state: AgentState) -> dict:
        prev_n = len(state["messages"])
        out = analyst_agent.invoke({"messages": state["messages"]})
        new_msgs = out["messages"][prev_n:]
        return {"messages": new_msgs}

    inject = context_injection_node(persona.id)

    g = StateGraph(AgentState)
    g.add_node("context_injection", inject)
    g.add_node("supervisor", supervisor_node)
    g.add_node("code_agent", run_code)
    g.add_node("ml_agent", run_ml)
    g.add_node("analyst", run_analyst)
    g.add_edge(START, "context_injection")
    g.add_edge("context_injection", "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "code_agent": "code_agent",
            "ml_agent": "ml_agent",
            "analyst": "analyst",
        },
    )
    g.add_edge("code_agent", END)
    g.add_edge("ml_agent", END)
    g.add_edge("analyst", END)
    return g.compile(checkpointer=get_langgraph_checkpointer())


# Per-persona compiled graph templates (prompts/tools frozen at compile time).
# Thread-safe via lock; **conversation state** lives in SqliteSaver (see checkpointing.py), not here.
_compiled: dict[str, object] = {}
_compile_lock = Lock()


def invalidate_compiled_graph_cache(persona_id: str | None = None) -> None:
    """Drop cached compiled graphs so prompts/tools reload (e.g. after persona switch)."""
    global _compiled
    with _compile_lock:
        if persona_id:
            _compiled.pop(persona_id.strip(), None)
        else:
            _compiled.clear()


def get_compiled_graph(persona_id: str):
    """Return compiled graph for this persona (separate prompts per lens)."""
    global _compiled
    with _compile_lock:
        if persona_id not in _compiled:
            _compiled[persona_id] = build_graph(persona_id)
        return _compiled[persona_id]
