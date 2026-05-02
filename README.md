# Shadow

**Shadow** is a local-first **forensic operations console** for fraud and disputes. It combines a **React** workspace UI, a **Tauri** desktop shell (optional), and a **Python FastAPI sidecar** that runs analytics (Polars, DuckDB, NetworkX, scikit-learn), an **agent** built on LangGraph/LangChain, and SQLite persistence—without sending case data to the cloud by default.

---

## What you can do

- **Cases and datasets** — Create cases, upload **CSV** evidence, preview rows,and keep a **DuckDB** projection for SQL-style exploration where ingest supports it.
- **Investigation workspace** — Three-pane UI: case files and memory, main workspace (timelines, evidence, ring graphs, chargeback tools, etc.), and an **Agent Console** with selectable **personas** (e.g. general analyst, fraud-ring specialist, chargeback specialist).
- **Agent and tools** — Chat invokes a LangGraph coordinator with tools for schema introspection, bot-cluster detection, fraud-ring graphs, code review, sandbox execution, thresholds, and more. LLM calls target a **local OpenAI-compatible endpoint** (default: **Ollama**).
- **Fraud ring network analysis** — Build linkage and payment graphs, community detection, and optional **GEXF** / **GraphML** export for **Gephi** or similar tools (`POST /api/cases/{case_id}/network/export`).
- **Chargeback / representment** — Workflows for dispute-oriented analysis and package generation; issuer simulation can use the same LLM stack when configured.
- **Realtime evidence board** — WebSocket channel at `/ws/cases/{case_id}/evidence` for board updates.

---

## Architecture


| Layer              | Technology                                       |
| ------------------ | ------------------------------------------------ |
| UI                 | React 19, TypeScript, Vite 8, Tailwind CSS 4     |
| Desktop (optional) | Tauri 2 (Rust)                                   |
| API                | FastAPI (Shadow Sidecar), Uvicorn                |
| Data               | SQLite (SQLAlchemy), Polars, DuckDB              |
| Graphs / ML        | NetworkX, scikit-learn                           |
| Agent              | LangGraph, LangChain, tools exposed to the model |


Rough data flow:

```text
Browser or Tauri shell
        │  HTTP / WS (loopback)
        ▼
FastAPI (backend/main.py)
        ├── SQLite (.data/shadow.db by default)
        ├── CSV / DuckDB artifacts under .data/storage/
        └── LangGraph chat + tool execution
```

---

## Prerequisites


| Requirement              | Notes                                                                                                                                                      |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Node.js**              | Current LTS recommended; used for Vite and Tauri CLI.                                                                                                      |
| **Python**               | **3.11+** (see `pyproject.toml`).                                                                                                                          |
| **Rust**                 | Needed only if you build or run **Tauri** (`rustup`, stable toolchain).                                                                                    |
| **Ollama** (recommended) | Local LLM for chat, code review, and representment simulation. Install [Ollama](https://ollama.com/) and pull a model (e.g. `llama3.2` to match defaults). |


---

## Quick start

### 1. Clone and install frontend dependencies

```bash
cd shadow
npm install
```

### 2. Python environment and backend package

From the repository root (so `backend` is importable):

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
# or: uv pip install -e .
```

### 3. Run the sidecar (FastAPI)

```bash
export PYTHONPATH="$(pwd)"   # if not using editable install that sets this
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8742
```

The API serves interactive docs at **[http://127.0.0.1:8742/docs](http://127.0.0.1:8742/docs)**.

### 4. Run the web UI

In another terminal:

```bash
npm run dev
```

Open **[http://localhost:5173](http://localhost:5173)**. The UI talks to the sidecar at `http://127.0.0.1:8742` via `VITE_API_BASE` or the default in `src/lib/api.ts`.

### 5. (Optional) Run everything through Tauri

Tauri starts Vite in dev, spawns the Python sidecar with matching port, and uses the Tauri `get_api_base_url` command so the UI always hits the embedded server.

```bash
npm run tauri:dev
```

Requires a working **Rust** toolchain and platform-specific Tauri dependencies.

### Build & API troubleshooting

- **`CACError: Unused args: 'tauri', 'build'`** — Extra arguments were passed to **`npm run build`** (for example `npm run build tauri build`). npm forwards those to the script, and **Vite** treats them as invalid CLI args. Use **`npm run build`** alone for the web bundle, then **`npm run tauri:build`** for the desktop app (Tauri’s `beforeBuildCommand` already runs `npm run build`). For one shot: **`npm run desktop:build`**.

- **`curl http://127.0.0.1:8742/llm-preferences` → `Not Found`** — The process on **8742** is not this repo’s current **`backend.main:app`** (old code, wrong working directory, or a different app). Stop it, **`cd`** to the repository root, set **`PYTHONPATH`** to that root (see step 3 above), then start Uvicorn again. Sanity check: **`curl -s http://127.0.0.1:8742/health`** should return JSON including **`ollama_model`** and **`ollama_env_default`**. Open **`/docs`** on the same host to confirm you see the Shadow OpenAPI.

---

## Configuration

Settings load from environment variables with prefix `**SHADOW_`**, and from a `**.env**` file in the current working directory when you start Uvicorn (pydantic-settings).


| Variable                     | Purpose                                                                 | Default                     |
| ---------------------------- | ----------------------------------------------------------------------- | --------------------------- |
| `SHADOW_API_HOST`            | Bind address for Uvicorn (you still pass `--host` to uvicorn if needed) | `127.0.0.1`                 |
| `SHADOW_API_PORT`            | Port encoded in `settings.api_port` and used by tooling                 | `8742`                      |
| `SHADOW_DATA_DIR`            | Root for SQLite (unless `DATABASE_URL` set) and `storage/`              | `<repo>/.data`              |
| `SHADOW_DATABASE_URL`        | Full SQLAlchemy URL; if empty, SQLite file under `DATA_DIR`             | *(auto)*                    |
| `SHADOW_WORKSPACE_DIR`       | Scratch/workspace for executions                                        | `<repo>/workspace`          |
| `SHADOW_OLLAMA_BASE_URL`     | OpenAI-compatible base URL                                              | `http://localhost:11434/v1` |
| `SHADOW_OLLAMA_MODEL`        | Model name passed to ChatOpenAI-compatible client                       | `llama3.2`                  |
| `SHADOW_OLLAMA_API_KEY`      | Placeholder key (Ollama ignores content)                                | `ollama`                    |
| `SHADOW_DEBUG_AGENT`         | Extra agent debugging                                                   | `false`                     |
| `SHADOW_DUCKDB_THREADS`      | Optional DuckDB thread count                                            | *(unset)*                   |
| `SHADOW_DUCKDB_MEMORY_LIMIT` | Optional DuckDB `memory_limit`                                          | *(unset)*                   |


**Model without editing `.env`:** The web console header has **Change model**, which saves `ollama_model` to `.data/preferences.json`. That value overrides `SHADOW_OLLAMA_MODEL` until you clear it in the same dialog. `GET /health` returns the effective `ollama_model`; `GET` / `PATCH /llm-preferences` read and update that override (same router as `/health`).

**Legacy:** If `SHADOW_API_PORT` is unset but `FRAUD_COPILOT_API_PORT` is set, that port is still honored (Python and Tauri). Similarly, `FRAUD_COPILOT_DEV_PYTHON` is a fallback for `SHADOW_DEV_PYTHON` when Tauri picks a Python binary.

**Frontend-only override:** `VITE_API_BASE` (e.g. `http://127.0.0.1:8742`) when not running inside Tauri.

---

## Data on disk

- **SQLite** — Default file: `**.data/shadow.db*`*. If that file does not exist but `**.data/fraud_copilot.db**` does (older installs), the app continues to use the legacy file until you migrate manually.
- **Datasets** — `.data/storage/datasets/` (managed when you upload CSVs).
- **DuckDB** — `.data/storage/duckdb/` per case when ingest creates DuckDB projections.
- **Sidecar preferences** — `.data/preferences.json` (optional keys such as `ollama_model`, written from the console **Change model** dialog).

Do not commit `.data/` or `.venv/`; treat them as local state.

---

## Useful npm scripts


| Script                        | Command               |
| ----------------------------- | --------------------- |
| Dev server                    | `npm run dev`         |
| Production build (web assets) | `npm run build`       |
| Lint                          | `npm run lint`        |
| Tauri dev                     | `npm run tauri:dev`   |
| Tauri release build           | `npm run tauri:build` |


---

## API overview

Routers are mounted from `backend/main.py`. Notable groups:

- `**GET /health`** — Liveness; includes `ollama_reachable`, effective `ollama_model`, `ollama_env_default` (`SHADOW_OLLAMA_MODEL`), and `ollama_using_override` when the default Ollama URL responds.
- `**GET /ollama-models**` — Tags from the local Ollama `/api/tags` endpoint (for the console model picker).
- `**GET**` / `**PATCH /llm-preferences**` — Read or update the optional on-disk `ollama_model` override (JSON body on PATCH: `{ "ollama_model": "<tag>" | null }`). Same contract at **`/api/preferences/llm`** for older clients.
- `**/api/cases**` — CRUD, upload, preview, activity, evidence payloads, leads; **`DELETE /api/cases/{id}`** removes one case and its ingested files + warehouse rows; **`POST`** or **`DELETE /api/cases/purge-all`** clears every case (local reset).
- `**POST /api/cases/{id}/network/rings**` — Fraud ring analysis JSON for the UI graph.
- `**POST /api/cases/{id}/network/export**` — **GEXF** or **GraphML** download for external graph tools.
- `**POST /api/chat`** — Agent conversation with optional `case_id` and persona.
- `**/api/personas**` — Persona metadata for the console selector.
- `**/api/agent**` — Agent-related utilities.
- `**/ws/cases/{case_id}/evidence**` — Evidence board websocket.

For the full contract, use **OpenAPI** at `/docs` while the sidecar is running.

---

## Network export (Gephi / Cytoscape)

1. Create a case and upload a CSV.
2. Call `**POST /api/cases/{case_id}/network/export`** with JSON body, for example:

```json
{
  "export_format": "gexf",
  "account_column": null,
  "payer_column": null,
  "payee_column": null,
  "amount_column": null
}
```

Omit overrides to use automatic column detection consistent with the ring analyzer. The response is XML (`application/xml`) suitable for **Gephi** (GEXF) or tools that consume **GraphML**.

The desktop UI also offers download buttons in the fraud-ring section once a dataset exists on the case.

---

## Security and privacy notes

- The stack is designed for **local** investigation: bind to loopback in development, and treat the machine as the trust boundary.
- **RestrictedPython** and related guards participate in controlled execution paths; still treat uploaded CSVs and operator-supplied code as untrusted input.
- Enable OS disk encryption and access controls for `.data/` if you handle sensitive finance or PII.

---

## Troubleshooting


| Symptom                            | Things to check                                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------------------------------ |
| UI shows sidecar **down**          | Uvicorn running? Port **8742** free? `curl http://127.0.0.1:8742/health`                         |
| **Ollama** dot red in header       | Is Ollama running? Model pulled? `SHADOW_OLLAMA_*` matches your setup?                           |
| `**ModuleNotFoundError: backend`** | Run from repo root with `PYTHONPATH` set, or use `pip install -e .`                              |
| Tauri cannot start Python          | Set `**SHADOW_DEV_PYTHON**` (or legacy `FRAUD_COPILOT_DEV_PYTHON`) to your `python3` in `.venv`. |
| CSV upload fails                   | Filenames must end in `**.csv**`; see API error body for validation details.                     |


---

## Project layout (high level)

```text
shadow/
├── backend/           # FastAPI app, routers, agent, tools, database
├── src/               # React application
├── src-tauri/         # Tauri shell (Rust) + bundle config
├── pyproject.toml     # Python package metadata and dependencies
├── package.json       # Node scripts and frontend deps
└── index.html         # Vite HTML shell
```

---

## Contributing and development

- Typecheck and bundle: `**npm run build**`
- Python: run tests if/when present in your branch; keep **3.11+** compatibility.
- After changing dependencies: update lockfiles as appropriate (`package-lock.json`, uv/pip).

---

## License

License not specified in this repository; add a `LICENSE` file if you distribute the project.