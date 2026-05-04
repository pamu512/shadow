# Architecture

## High-level diagram

```text
┌─────────────────────────────────────────────────────────────┐
│  Client: React 19 + Vite + TypeScript + Tailwind            │
│  • Three-pane workspace (cases, tools, agent console)       │
│  • Optional: Tauri 2 WebView (desktop)                      │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP(S) + WebSocket (loopback)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Shadow Sidecar: FastAPI (`backend/main.py`)                │
│  • REST routers under `/api/*`, `/health`, `/llm-preferences`│
│  • WS: `/ws/cases/{case_id}/evidence`                       │
│  • LangGraph supervisor → code / ML / analyst subgraphs    │
└───────┬─────────────────────────────────────┬─────────────┘
        │                                     │
        ▼                                     ▼
┌────────────────────────┐         ┌─────────────────────────────────┐
│ SQLite / Postgres      │         │ Files & analytics               │
│ SQLAlchemy             │         │ • CSV storage + delimiter sniff │
│ • AsyncSession (HTTP)  │         │ • DuckDB per case               │
│ • Sync sessions (agent)│         │ • Warehouse DuckDB + ACL views  │
└────────────────────────┘         │ • Polars / NetworkX / sandbox   │
                                    │ • sklearn + optional ONNX RT    │
                                    └─────────────────────────────────┘
```

## Repository layout

| Path | Role |
| ---- | ---- |
| `backend/` | FastAPI app: `main.py`, `api/routers/`, `agent/` (LangGraph), `tools/`, `database/`, `schemas/` |
| `src/` | React application (components, hooks, `lib/api.ts`) |
| `src-tauri/` | Tauri Rust crate: window, **Python sidecar spawn**, `get_api_base_url`, `restart_sidecar` |
| `pyproject.toml` | Python package `shadow-backend`, runtime dependencies |
| `package.json` | Node scripts, frontend + Tauri CLI deps |
| `.data/` | **Local only** — SQLite (or Postgres data elsewhere), uploads, DuckDB, `preferences.json`, optional `tool_confidence.onnx` (gitignored) |
| `workspace/` | Scratch for sandbox runs; ephemeral **`cwd_<uuid>/`** dirs during subprocess/Pyodide Python (gitignored as configured) |

## Agent runtime

- **Graph:** `backend/agent/graph.py` — `context_injection` → **supervisor** (structured route) → **code_agent** | **ml_agent** | **analyst** (ReAct with tools).
- **Personas:** `backend/agent/personas.py` + `backend/agents/registry.py` define lenses, allowed tools, and system prompts.
- **Tools:** LangChain `@tool` wrappers in `backend/agent/tools_langchain.py`; heavy logic in `backend/tools/`.

See [AGENT.md](./AGENT.md) for personas and tool list.

## Realtime

- **`EvidenceHub`** (`backend/realtime/evidence_hub.py`) fans out lead and board events to WebSocket subscribers per `case_id`.

## Warehouse access control

- **`backend/data/warehouse_access.py`** builds a unique DuckDB schema (for example `whacl_<uuid>`), creates **views** over `main.warehouse_events`, `main.entity_occurrences`, and `main.entity_map` filtered to an **allowed case id set** (the active case plus **case share** targets), runs `SET schema = …`, then tears the schema down after the query.
- **`warehouse_query_tool`** / **`global_search`** install this ACL around user SQL or internal selects so isolation is **database-enforced**.

## Sandboxing

- **Subprocess / Pyodide:** each Python job uses **`workspace/cwd_<uuid>/`** as **cwd**; Docker mode optionally applies **`--storage-opt size=1G`** only after a one-time capability probe (`backend/sandbox/docker_runner.py`).

## CORS

`backend/main.py` allows dev origins (`localhost:5173`, `127.0.0.1:5173`, Tauri schemes). Extend if you add another dev host.
