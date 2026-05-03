# Configuration

Configuration is read from **environment variables** (prefix `SHADOW_`) and from a **`.env`** file in the working directory when you start Uvicorn. Pydantic settings live in `backend/config.py`.

## Core API & data

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `SHADOW_API_HOST` | Documented bind hint (you still pass `--host` to uvicorn) | `127.0.0.1` |
| `SHADOW_API_PORT` | HTTP port for the sidecar; Tauri encodes the same port | `8742` |
| `SHADOW_DATA_DIR` | Root for SQLite (unless `DATABASE_URL` set) and storage | `<repo>/.data` |
| `SHADOW_DATABASE_URL` | Full SQLAlchemy URL; if unset, SQLite under `DATA_DIR`. Use `postgresql://...` (or `postgresql+psycopg://...`) for Postgres: **ORM + LangGraph checkpoints** share this URL. | *(auto)* |
| `SHADOW_INGESTION_PROVIDER` | `local` (Polars/DuckDB), `tarka` (require HTTP ETL), or `auto` (try Tarka when URL set) | `local` |
| `SHADOW_TARKA_ETL_BASE_URL` | Tarka service base URL; ingest posts to `{base}/ingest` | *(empty)* |
| `SHADOW_LLM_TOOL_CONFIDENCE` | If `true`, LLM scores tool JSON for RFI; if `false`, fast deterministic heuristics | `false` |
| `SHADOW_WORKSPACE_DIR` | Sandbox / scratch files | `<repo>/workspace` |

## LLM (Ollama / OpenAI-compatible)

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `SHADOW_OLLAMA_BASE_URL` | Base URL for chat client | `http://localhost:11434/v1` |
| `SHADOW_OLLAMA_MODEL` | Model id (e.g. `llama3.2`) | `llama3.2` |
| `SHADOW_OLLAMA_API_KEY` | Placeholder; Ollama ignores value | `ollama` |
| `SHADOW_DEBUG_AGENT` | Extra agent logging | `false` |

## Code sandbox (Python / R)

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `SHADOW_SANDBOX_MODE` | `subprocess` (AST-validated local run), `docker` (`docker run --network none`), or `pyodide` (WASM via Node.js) | `pyodide` |
| `SHADOW_SANDBOX_DOCKER_IMAGE` | Python image when mode is `docker` (install Polars/etc. in a custom image if needed) | `python:3.12-slim` |
| `SHADOW_SANDBOX_DOCKER_R_IMAGE` | R image when mode is `docker` | `rocker/r-ver:4.4.0` |

**UI override:** The header **Change model** writes `ollama_model` to **`.data/preferences.json`**, which overrides `SHADOW_OLLAMA_MODEL` until cleared in the same dialog. `GET /health` reports the effective model.

## DuckDB tuning (optional)

| Variable | Purpose |
| -------- | ------- |
| `SHADOW_DUCKDB_THREADS` | Thread count |
| `SHADOW_DUCKDB_MEMORY_LIMIT` | e.g. `4GB` |

## Frontend

| Variable | Purpose |
| -------- | ------- |
| `VITE_API_BASE` | API root for **production** builds / `vite preview` when not using Tauri invoke (e.g. `http://127.0.0.1:8742`) |
| `VITE_PROXY_TARGET` | **Dev only:** where Vite proxies `/api`, `/health`, `/ws`, etc. (default `http://127.0.0.1:8742`) |

During **`npm run dev`** / **`tauri dev`**, the UI uses **same-origin** paths (`/api/...`); Vite forwards them to `VITE_PROXY_TARGET`. You still need uvicorn listening on that target.

## Legacy aliases

Still honored where noted in code:

- `FRAUD_COPILOT_API_PORT` → port if `SHADOW_API_PORT` unset  
- `FRAUD_COPILOT_DEV_PYTHON` → Python binary hint for Tauri dev (`SHADOW_DEV_PYTHON` preferred)

## Tauri / dev Python

| Variable | Purpose |
| -------- | ------- |
| `SHADOW_DEV_PYTHON` | Absolute path to `python3` in `.venv` if auto-detection fails |

## Data paths (on disk)

- **SQLite:** `.data/shadow.db` (legacy: `.data/fraud_copilot.db`)
- **Datasets / DuckDB:** under `.data/storage/`
- **Preferences:** `.data/preferences.json`
- **LangGraph checkpoints:** `.data/langgraph_checkpoints.sqlite` when using SQLite; **Postgres checkpoint tables** when `SHADOW_DATABASE_URL` is a Postgres DSN  
- **Global warehouse (DuckDB):** `.data/warehouse/<tenant_id>/warehouse.duckdb` (default tenant `default`)
- **RAG knowledge index:** `.data/rag_knowledge.sqlite`

Do not commit `.data/` or `.venv/`.
