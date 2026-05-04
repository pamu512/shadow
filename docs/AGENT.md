# Agent, personas, and tools

## Overview

Shadow’s **Agent Console** sends messages to `**POST /api/chat`**, which runs a **LangGraph** application (`backend/agent/graph.py`):

1. **Context injection** — Injects case/schema hints where configured (`reasoning_hooks.py`).
2. **Supervisor** — Classifies the last user turn and routes to **code**, **ML**, or **analyst** subgraph.
3. **Specialist** — Each subgraph is a **ReAct** agent (`create_react_agent`) with its own tool set and system prompt.

The compiled graph is **cached per persona**; `thread_reset` on the chat request invalidates the cache for that persona.

## Personas (lenses)

Personas are defined in `**backend/agents/registry.py`** and surfaced to the UI via `**GET /api/personas`**. Each persona includes:

- `system_prompt` + optional suffix (warehouse rules, confidence policy)
- `allowed_tool_names` — strict allowlist for the analyst ReAct agent
- `recommended_tools` — hints for documentation / UI

Examples (not exhaustive — see registry):


| Persona id                 | Focus                                                                  |
| -------------------------- | ---------------------------------------------------------------------- |
| `general`                  | Cross-case warehouse, overlap search, trust/velocity, Humanoid linkage |
| `chargeback_specialist`    | Disputes, representment, chargeback risk                               |
| `bot_hunter`               | Bot clusters, hardware/IP forensics                                    |
| `fraud_ring_detective`     | Graph rings, roles                                                     |
| `fraud_playbook_architect` | Extended playbook + extra tools (see `fraud_playbook_context.md`)      |


## Analyst tools (representative)

Implemented in `**backend/agent/tools_langchain.py`** (names must match allowlists):

- `get_dataset_schema` — CSV column summary for active case  
- `execute_in_sandbox` — Python/R in a restricted environment  
- `emit_lead` — Create evidence-board lead  
- `chargeback_trust_velocity_tool`, `analyze_chargeback_risk_tool` — dispute workflows  
- `detect_bot_clusters_tool`, `find_fraud_rings_tool`, `profile_fraud_ring_roles_tool`  
- `search_historical_overlap_tool`, `warehouse_query_tool`, `warehouse_search_text_tool`  
- `humanoid_stress_test_linkage_tool`  
- Plus code/ML subgraph tools: `review_script_tool`, `scaffold_code_tool`, `optimize_thresholds_tool`, …

## Chat request shape

```json
{
  "messages": [
    { "role": "user", "content": "…" },
    { "role": "assistant", "content": "…" }
  ],
  "case_id": "<uuid or null>",
  "persona_id": "general",
  "thread_reset": false
}
```

Responses return `messages` (full transcript slice) plus optional `debug` when `SHADOW_DEBUG_AGENT` is enabled.

## Tooling discipline (for contributors)

- Tools are invoked by the **runtime**, not by pasting JSON “fake tool calls” in model prose.
- **Planning-only** questions (e.g. “hypotheses to validate first”) should be answered in **plain English** without inventing entities or tool traces.

Prompt assembly: `backend/agent/coordinator.py` (`build_analyst_system_prompt`, supervisor strings).

## LLM backend

LangChain `**ChatOpenAI`**-compatible client points at **Ollama** by default (`SHADOW_OLLAMA_`*). Any OpenAI-compatible endpoint can be used if URLs/keys are adjusted.

## Tool output confidence (RFI / UI)

Per-tool JSON can receive a **confidence score** in `[0, 1]` for analyst-facing UI:

1. If the payload already includes `confidence_score`, that value wins.
2. If `**SHADOW_LLM_TOOL_CONFIDENCE=true`**, a small structured LLM call scores the payload (with heuristic fallback on errors).
3. Otherwise, if `**<SHADOW_DATA_DIR>/tool_confidence.onnx`** exists, **ONNX Runtime** runs a lightweight forest on encoded features (`ok`, row count band, `truncated`, `global_hits`, severity-style flags). Train or refresh the file with `**python -m backend.agent.train_confidence_model`**.
4. If no ONNX file is present, **deterministic heuristics** in `backend/agent/tool_confidence.py` apply.

Warehouse tools still benefit from **DuckDB ACL views** (see [ARCHITECTURE.md](./ARCHITECTURE.md)); confidence scoring is separate from row isolation.