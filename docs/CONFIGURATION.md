# Configuration

Configuration is read from **environment variables** (prefix `SHADOW_`) and from a `**.env`** file in the working directory when you start Uvicorn. Pydantic settings live in `backend/config.py`.

## Core API & data


| Variable                     | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                            | Default            |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| `SHADOW_API_HOST`            | Documented bind hint (you still pass `--host` to uvicorn)                                                                                                                                                                                                                                                                                                                                                                                          | `127.0.0.1`        |
| `SHADOW_API_PORT`            | HTTP port for the sidecar; Tauri encodes the same port                                                                                                                                                                                                                                                                                                                                                                                             | `8742`             |
| `SHADOW_DATA_DIR`            | Root for SQLite (unless `SHADOW_DATABASE_URL` is set) and on-disk storage artifacts                                                                                                                                                                                                                                                                                                                                                                | `<repo>/.data`     |
| `SHADOW_DATABASE_URL`        | Full SQLAlchemy URL for **both** the sync engine (migrations, LangGraph tool paths) and the async engine used by FastAPI routers. If unset, SQLite under `DATA_DIR`. For Postgres use `postgresql://...` or `postgresql+psycopg://...` (sync); the app derives `**postgresql+asyncpg://...`** for HTTP handlers. For SQLite the async URL becomes `**sqlite+aiosqlite://...`**. Install `**asyncpg`** / `**aiosqlite**` when using those backends. | *(auto)*           |
| `SHADOW_INGESTION_PROVIDER`  | `local` (Polars/DuckDB), `tarka` (require HTTP ETL), or `auto` (try Tarka when URL set)                                                                                                                                                                                                                                                                                                                                                            | `local`            |
| `SHADOW_TARKA_ETL_BASE_URL`  | Tarka service base URL; ingest posts to `{base}/ingest`                                                                                                                                                                                                                                                                                                                                                                                            | *(empty)*          |
| `SHADOW_LLM_TOOL_CONFIDENCE` | If `true`, LLM scores tool JSON for RFI; if `false`, use **ONNX** model when `tool_confidence.onnx` exists under `SHADOW_DATA_DIR`, else fast heuristic fallback                                                                                                                                                                                                                                                                                   | `false`            |
| `SHADOW_WORKSPACE_DIR`       | Sandbox / scratch files                                                                                                                                                                                                                                                                                                                                                                                                                            | `<repo>/workspace` |


## LLM (Ollama / OpenAI-compatible)


| Variable                 | Purpose                           | Default                     |
| ------------------------ | --------------------------------- | --------------------------- |
| `SHADOW_OLLAMA_BASE_URL` | Base URL for chat client          | `http://localhost:11434/v1` |
| `SHADOW_OLLAMA_MODEL`    | Model id (e.g. `llama3.2`)        | `llama3.2`                  |
| `SHADOW_OLLAMA_API_KEY`  | Placeholder; Ollama ignores value | `ollama`                    |
| `SHADOW_DEBUG_AGENT`     | Extra agent logging               | `false`                     |


## Code sandbox (Python / R)


| Variable                        | Purpose                                                                                                         | Default              |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------- |
| `SHADOW_SANDBOX_MODE`           | `subprocess` (AST-validated local run), `docker` (`docker run --network none`), or `pyodide` (WASM via Node.js) | `pyodide`            |
| `SHADOW_SANDBOX_DOCKER_IMAGE`   | Python image when mode is `docker` (install Polars/etc. in a custom image if needed)                            | `python:3.12-slim`   |
| `SHADOW_SANDBOX_DOCKER_R_IMAGE` | R image when mode is `docker`                                                                                   | `rocker/r-ver:4.4.0` |


**Docker storage limits:** On first use, the sidecar runs a short probe (`docker run … --storage-opt size=10M alpine …`). If the daemon rejects `storage-opt`, `**--storage-opt size=1G` is omitted** from Python/R sandbox runs so hosts without compatible storage drivers still work.

**Subprocess / Pyodide cwd:** For local Python execution, each run creates `**workspace/cwd_<uuid>/`**, writes the generated script there, sets the process **cwd** to that directory, and deletes it afterward—so concurrent runs cannot observe each other’s relative paths. Plot output still uses a separate ephemeral directory under `SHADOW_WORKSPACE_DIR`.

**UI override:** The header **Change model** writes `ollama_model` to `**.data/preferences.json`**, which overrides `SHADOW_OLLAMA_MODEL` until cleared in the same dialog. `GET /health` reports the effective model.

## DuckDB tuning (optional)


| Variable                     | Purpose      |
| ---------------------------- | ------------ |
| `SHADOW_DUCKDB_THREADS`      | Thread count |
| `SHADOW_DUCKDB_MEMORY_LIMIT` | e.g. `4GB`   |


## Frontend


| Variable            | Purpose                                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------------------- |
| `VITE_API_BASE`     | API root for **production** builds / `vite preview` when not using Tauri invoke (e.g. `http://127.0.0.1:8742`) |
| `VITE_PROXY_TARGET` | **Dev only:** where Vite proxies `/api`, `/health`, `/ws`, etc. (default `http://127.0.0.1:8742`)              |


During `**npm run dev`** / `**tauri dev`**, the UI uses **same-origin** paths (`/api/...`); Vite forwards them to `VITE_PROXY_TARGET`. You still need uvicorn listening on that target.

## Legacy aliases

Still honored where noted in code:

- `FRAUD_COPILOT_API_PORT` → port if `SHADOW_API_PORT` unset  
- `FRAUD_COPILOT_DEV_PYTHON` → Python binary hint for Tauri dev (`SHADOW_DEV_PYTHON` preferred)

## Tauri / dev Python


| Variable            | Purpose                                                       |
| ------------------- | ------------------------------------------------------------- |
| `SHADOW_DEV_PYTHON` | Absolute path to `python3` in `.venv` if auto-detection fails |


## Data paths (on disk)

- **SQLite:** `.data/shadow.db` (legacy: `.data/fraud_copilot.db`)
- **Datasets / DuckDB:** under `.data/storage/`
- **Preferences:** `.data/preferences.json`
- **LangGraph checkpoints:** `.data/langgraph_checkpoints.sqlite` when using SQLite; **Postgres checkpoint tables** when `SHADOW_DATABASE_URL` is a Postgres DSN  
- **Global warehouse (DuckDB):** `.data/warehouse/<tenant_id>/warehouse.duckdb` (default tenant `default`). Queries from the API and agent tools are scoped with an **ephemeral DuckDB schema** and **views** filtered to allowed case IDs (and explicit **case shares**), not regex rewriting of user SQL.
- **RAG knowledge index:** `.data/rag_knowledge.sqlite`
- **Tool confidence ONNX:** `<SHADOW_DATA_DIR>/tool_confidence.onnx` — optional; trains a small `RandomForest` on synthetic features and exports ONNX:
  ```bash
  python -m backend.agent.train_confidence_model
  ```
  Requires **`onnxruntime`** and **`skl2onnx`** (declared in `pyproject.toml`). If the file is missing, non-LLM confidence scoring falls back to heuristics.

## CSV ingestion (local)

When `SHADOW_INGESTION_PROVIDER=local`, CSV reads use **encoding detection** plus `**csv.Sniffer`** on a sample of the file to pick a **delimiter** before Polars (and Pandas fallback) parsing—helpful for `;`- or tab-separated exports.

Do not commit `.data/` or `.venv/`.