# Troubleshooting

## Chat: “could not reach … 8742” / “Load failed”

| Cause | What to do |
| ----- | ---------- |
| **No Python on 8742** | In dev, Vite **proxies** `/api` → `http://127.0.0.1:8742` by default. Start uvicorn there, or set **`VITE_PROXY_TARGET`** to wherever the API runs. |
| **Browser tab only** (`localhost:5173`) | Same as above: sidecar must be running; the UI no longer calls `:8742` directly in dev—it uses the proxy. |
| **Sidecar exited** (venv / import error) | In **Tauri**, use **Restart API**. From terminal: `export PYTHONPATH="$(pwd)"` then `.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8742`. |
| **Port 8742 in use** | Stop the other process or set `SHADOW_API_PORT` + **`VITE_PROXY_TARGET`** to match. |
| **Tauri window won’t open / setup error** | If the sidecar never binds, startup now **fails fast** with a Rust error—read the terminal message. |

## Sidecar green but chat fails

Health is polled periodically, but if the process dies between polls, use **Recheck health** or **Restart API** (Tauri).

## `curl …/llm-preferences` → Not Found

Something else is bound to **8742**, or the wrong app is running. Stop it, `cd` to the repo root, set `PYTHONPATH`, start `backend.main:app`, confirm **`/docs`** shows **Shadow Sidecar**.

## `ModuleNotFoundError: backend`

Run from repository root with `PYTHONPATH=$(pwd)` or use `pip install -e .`.

## Tauri cannot find Python

Set **`SHADOW_DEV_PYTHON`** to your `.venv/bin/python3` absolute path.

## `npm run build` / CAC / extra args

Use **`npm run build`** alone for the web bundle. Desktop: **`npm run desktop:build`** or **`npm run tauri:build`** (Tauri runs `beforeBuildCommand`).

## Ollama dot red

- Is `ollama serve` running?
- Does `ollama list` include your model?
- Match `SHADOW_OLLAMA_*` or use **Change model** in the header.

## CSV upload rejected

Filenames must end in **`.csv`**; read the API error body for validation details.

## ESLint / TypeScript

```bash
npm run lint
npm run build
```

## Python tests

Run any tests present in your branch from the repo root with `PYTHONPATH` set or editable install active.
