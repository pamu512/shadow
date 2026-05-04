# Shadow

**Shadow** is a **local-first forensic operations console** for fraud and disputes. It combines a **React** workspace, an optional **Tauri 2** desktop shell, and a **Python FastAPI** sidecar that runs **Polars**, **DuckDB**, **NetworkX**, **scikit-learn**, and a **LangGraph / LangChain** agent—without sending case data to the cloud by default.

---

## Documentation

| Resource | Description |
| -------- | ----------- |
| **[docs/README.md](./docs/README.md)** | Index of all guides |
| **[docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md)** | Install, first run, verify health |
| **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** | System diagram, folders, realtime |
| **[docs/CONFIGURATION.md](./docs/CONFIGURATION.md)** | Environment variables & paths |
| **[docs/API.md](./docs/API.md)** | HTTP / WebSocket map → use **`/docs`** for full OpenAPI |
| **[docs/AGENT.md](./docs/AGENT.md)** | Personas, tools, chat contract |
| **[docs/TAURI_DESKTOP.md](./docs/TAURI_DESKTOP.md)** | Desktop app, sidecar, ports, Restart API |
| **[docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)** | Common failures and fixes |

---

## Table of contents

- [What you can do](#what-you-can-do)
- [Architecture (summary)](#architecture-summary)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Running modes: desktop vs browser](#running-modes-desktop-vs-browser)
- [Configuration (summary)](#configuration-summary)
- [Data on disk](#data-on-disk)
- [npm scripts](#npm-scripts)
- [API surface (summary)](#api-surface-summary)
- [Network export (Gephi / Cytoscape)](#network-export-gephi--cytoscape)
- [Security & privacy](#security--privacy)
- [Project layout](#project-layout)
- [Development & contributing](#development--contributing)
- [License](#license)

---

## What you can do

- **Cases & datasets** — Create cases, upload **CSV** evidence, preview rows, and keep a **DuckDB** projection where ingest supports it.
- **Investigation workspace** — Three-pane UI: case registry, main workspace (timelines, evidence, ring graphs, chargeback tools, ATO, bots, etc.), and an **Agent Console** with selectable **personas**.
- **Agent & tools** — LangGraph routes to specialists with tools for schema, bot clusters, fraud rings, warehouse SQL, code review, sandbox execution, thresholds, chargeback / representment flows, and more. LLMs default to **local Ollama** (OpenAI-compatible API).
- **Fraud ring analysis** — Linkage graphs, communities, optional **GEXF** / **GraphML** export (`POST /api/cases/{case_id}/network/export`).
- **Chargeback / representment** — Dispute-oriented scans, manifests, issuer-style simulation (LLM-backed when configured).
- **Evidence board** — Realtime updates via **`WS /ws/cases/{case_id}/evidence`**.

---

## Architecture (summary)

| Layer | Technology |
| ----- | ---------- |
| UI | React 19, TypeScript, Vite 8, Tailwind CSS 4 |
| Desktop (optional) | Tauri 2 (Rust) — spawns Python, exposes API base + **Restart API** |
| API | FastAPI, Uvicorn (**async** database sessions for routers; sync engine retained for LangGraph and migrations) |
| Persistence | SQLite or Postgres (SQLAlchemy); CSV + DuckDB artifacts under `.data/` |
| Graphs / ML | NetworkX, scikit-learn, optional **ONNX Runtime** for fast tool-confidence scoring |
| Agent | LangGraph, LangChain tools |

```text
React (Vite) ──HTTP/WS──► FastAPI (backend.main)
                              ├── SQLite / Postgres (async ORM in routers)
                              ├── storage / DuckDB (per case + global warehouse)
                              └── LangGraph (chat + tools; sync DB where needed)
```

**Deep dive:** [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)

---

## Prerequisites

| Requirement | Notes |
| ----------- | ----- |
| **Node.js** | Current LTS; drives Vite and Tauri CLI |
| **Python 3.11+** | `pyproject.toml` |
| **Rust** | Only for Tauri (`rustup`, stable) |
| **Ollama** (recommended) | [ollama.com](https://ollama.com/) — e.g. `ollama pull llama3.2` |

---

## Quick start

```bash
git clone <repo-url> shadow && cd shadow
npm install
python3.11 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

**Recommended — one command (desktop + API + Vite):**

```bash
npm run tauri:dev
```

**Alternative — two terminals (web + API):**

```bash
# Terminal 1
export PYTHONPATH="$(pwd)"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8742

# Terminal 2
npm run dev
# Open http://localhost:5173 — set VITE_API_BASE if needed
```

- **OpenAPI:** [http://127.0.0.1:8742/docs](http://127.0.0.1:8742/docs)  
- **Health:** `curl -s http://127.0.0.1:8742/health`

**Step-by-step:** [docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md)

---

## Running modes: desktop vs browser

| Mode | How | API |
| ---- | --- | --- |
| **Tauri desktop** | `npm run tauri:dev` | Sidecar **auto-spawned**; use **Restart API** in the header if chat fails |
| **Browser only** | `npm run dev` | You **must** run Uvicorn separately (or point `VITE_API_BASE` at any reachable Shadow API) |

> A browser tab on **5173** alone does **not** start Python. Chat requires a running sidecar.

**Details:** [docs/TAURI_DESKTOP.md](./docs/TAURI_DESKTOP.md)

---

## Configuration (summary)

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `SHADOW_API_PORT` | Sidecar port (Tauri uses the same) | `8742` |
| `SHADOW_DATA_DIR` | Default root for SQLite file (when URL not set), uploads, and `tool_confidence.onnx` | `<repo>/.data` |
| `SHADOW_DATABASE_URL` | SQLAlchemy URL; FastAPI uses an **async** driver derived from it (`sqlite+aiosqlite`, `postgresql+asyncpg`) when applicable | *(see [CONFIGURATION.md](./docs/CONFIGURATION.md))* |
| `SHADOW_WORKSPACE_DIR` | Sandbox scratch; subprocess runs use a **unique** `cwd_<uuid>` per execution | `<repo>/workspace` |
| `SHADOW_OLLAMA_BASE_URL` | LLM base URL | `http://localhost:11434/v1` |
| `SHADOW_OLLAMA_MODEL` | Model id | `llama3.2` |
| `SHADOW_DEBUG_AGENT` | Verbose agent debug JSON | `false` |
| `VITE_API_BASE` | Frontend API root when **not** in Tauri | `http://127.0.0.1:8742` (fallback in code) |

**Model override in UI:** Header **Change model** → `.data/preferences.json`.

**Full table + legacy aliases:** [docs/CONFIGURATION.md](./docs/CONFIGURATION.md)

---

## Data on disk

- **SQLite / Postgres** — default SQLite file under `SHADOW_DATA_DIR`: `shadow.db` (legacy: `fraud_copilot.db`); override with `SHADOW_DATABASE_URL`.
- **Uploads / DuckDB** — `.data/storage/`
- **Preferences** — `.data/preferences.json`
- **Tool confidence ONNX** (optional) — `.data/tool_confidence.onnx`; generate with `python -m backend.agent.train_confidence_model` after `pip install -e .` (see [docs/CONFIGURATION.md](./docs/CONFIGURATION.md)).

Do **not** commit `.data/` or `.venv/`.

---

## npm scripts

| Script | Purpose |
| ------ | ------- |
| `npm run dev` | Vite dev server |
| `npm run build` | Typecheck + production web bundle |
| `npm run lint` | ESLint |
| `npm run tauri:dev` | Desktop + Vite + sidecar |
| `npm run tauri:build` | Desktop release (runs `beforeBuildCommand` → `npm run build`) |
| `npm run desktop:build` | `npm run build && tauri build` |

---

## API surface (summary)

Routers are mounted in **`backend/main.py`**. Highlights:

- **`GET /health`**, **`GET/PATCH /llm-preferences`**, **`GET /ollama-models`**
- **`/api/cases/*`** — CRUD, upload, preview, activity, evidence, leads, purge, **case shares** (`GET`/`POST` `/api/cases/{id}/shares`, `DELETE` … `/shares/{viewer_case_id}`)
- **`POST /api/chat`** — Agent (optional `case_id`, `persona_id`, `thread_reset`)
- **`/api/cases/{id}/network/*`**, **`/api/cases/{id}/chargeback/*`**, **`/api/cases/{id}/bots/*`**, ATO routes
- **`POST /api/execute`**, **`/api/code-review`**, **`/api/scaffold`**, **`/api/optimize-thresholds`**
- **`/api/warehouse/*`** — global warehouse reads (queries run against **filtered views** in an ephemeral DuckDB schema scoped to allowed case IDs)
- **`WS /ws/cases/{case_id}/evidence`**

**Route map:** [docs/API.md](./docs/API.md) — **always prefer `/docs` live** for schemas and try-it-out.

---

## Network export (Gephi / Cytoscape)

`POST /api/cases/{case_id}/network/export` with body:

```json
{
  "export_format": "gexf",
  "account_column": null,
  "payer_column": null,
  "payee_column": null,
  "amount_column": null
}
```

Response is XML (`application/xml`) for **GEXF** or **GraphML**. Omit column overrides to use auto-detection aligned with the ring analyzer.

---

## Security & privacy

- Designed for **local** investigation: bind to **loopback** in dev; treat the machine as the trust boundary.
- **RestrictedPython** and sandbox policy constrain `execute` paths; still treat CSVs and user code as **untrusted**. Subprocess and Pyodide Python runs use a **dedicated working directory per run** under `SHADOW_WORKSPACE_DIR` so concurrent jobs cannot see each other’s cwd-relative paths.
- **Docker** sandbox mode probes **`--storage-opt`** once at startup; the size cap is applied only if the daemon supports it (avoids hard failures on drivers that reject `storage-opt`).
- **Warehouse isolation** is enforced in DuckDB via a temporary schema and **views** over `warehouse_events` / entity tables, not client-side SQL rewriting. **Case shares** explicitly grant another case read overlap into an owner case’s warehouse slice.
- Use disk encryption and OS access controls for `.data/` when handling sensitive PII.

---

## Project layout

```text
shadow/
├── backend/           # FastAPI, routers, agent/, tools/, database/, schemas/
├── src/               # React app (components, hooks, lib/api.ts)
├── src-tauri/         # Tauri Rust crate, capabilities, icons
├── docs/              # This documentation set
├── pyproject.toml     # Python package (shadow-backend)
├── package.json       # Node scripts & frontend deps
└── index.html         # Vite shell
```

---

## Development & contributing

```bash
npm run lint
npm run build
```

Python: keep **3.11+** compatibility; run tests from your branch when present. After dependency changes, refresh lockfiles (`package-lock.json`, pip/uv).

**Agent / persona edits:** `backend/agents/registry.py`, `backend/agent/coordinator.py`, `backend/agent/graph.py`.

**Troubleshooting:** [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)

---

## License

No `LICENSE` file is included in this repository yet; add one before distribution.
