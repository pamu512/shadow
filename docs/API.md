# HTTP & WebSocket API

The **authoritative contract** is **OpenAPI** served while the sidecar runs:

- **Swagger UI:** `http://127.0.0.1:8742/docs` (or your configured host/port)

Below is a **route map** by prefix. Paths are relative to the API root (e.g. `http://127.0.0.1:8742`).

## Health & preferences

| Method | Path | Notes |
| ------ | ---- | ----- |
| `GET` | `/health` | `ok`, `ollama_reachable`, effective `ollama_model`, overrides |
| `GET` | `/ollama-models` | Installed Ollama tags for the model picker |
| `GET` / `PATCH` | `/llm-preferences` | Read/update saved model override (also `/api/preferences/llm` for older clients) |

## Cases & evidence

| Prefix | Examples |
| ------ | -------- |
| `/api/cases` | List/create cases, upload CSV, preview, activity, activate, delete |
| `/api/cases/{id}/shares` | **Case sharing:** `GET` list, `POST` body `{ "viewer_case_id": "<uuid>" }`, `DELETE /api/cases/{id}/shares/{viewer_case_id}` |
| `/api/cases/{id}/evidence` | Evidence board payload (GET) |
| `/api/cases/{id}/leads/{lead_id}` | PATCH lead status |
| `DELETE` | `/api/cases/{id}`, `/api/cases/purge-all` (or POST purge — see router) |

## Chargeback & representment

Under **`/api/cases/{case_id}/chargeback/`** — analyze, manifest, simulate representment, zip package (see OpenAPI).

## Network (fraud rings)

| Method | Path |
| ------ | ---- |
| `POST` | `/api/cases/{case_id}/network/rings` |
| `POST` | `/api/cases/{case_id}/network/export` — body: `export_format` `gexf` \| `graphml` |

## Bots

| Method | Path |
| ------ | ---- |
| `POST` | `/api/cases/{case_id}/bots/detect` |
| `POST` | `/api/cases/{case_id}/bots/bulk-suspend` |

## ATO

Routes under **`/api/cases/...`** for ATO-oriented analysis (see `/docs`).

## Agent & chat

| Method | Path |
| ------ | ---- |
| `POST` | `/api/chat` — body: `messages`, optional `case_id`, `persona_id`, `thread_reset` |
| `GET` | `/api/personas` |
| Various | `/api/agent/*` — utilities |

## Code & ML

| Method | Path |
| ------ | ---- |
| `POST` | `/api/execute` — sandbox Python/R |
| `POST` | `/api/code-review` |
| `POST` | `/api/scaffold` |
| `POST` | `/api/optimize-thresholds` |

## Warehouse (global)

| Prefix | Role |
| ------ | ---- |
| `/api/warehouse/*` | Read-only warehouse SQL / text search (see router). The backend installs **filtered views** in a temporary DuckDB schema and sets the session schema so unqualified table names resolve only to rows allowed for the current case (plus any **shared** viewer cases). |

## Concurrency

Most **case-scoped** routers are **`async def`** and use **Async SQLAlchemy**; long synchronous work (LLM chat, DuckDB analytics, file-heavy tools) runs in a **thread pool** so the event loop stays responsive.

## WebSocket

- **`WS`** `/ws/cases/{case_id}/evidence` — evidence board stream; client may send ping text; disconnect on close.

## CORS

Origins allowed for browser dev are listed in `backend/main.py` (`CORSMiddleware`). Tauri uses the same loopback API.
