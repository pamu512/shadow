# Tauri desktop shell

## What Tauri does here

- Hosts the **same Vite-built React UI** in a native window (dev: loads `devUrl` **http://localhost:5173**).
- Spawns the **Python sidecar** on startup: `python -m uvicorn backend.main:app` with `PYTHONPATH` set to the repo root.
- Exposes **`get_api_base_url`** so the frontend resolves the API (default **http://127.0.0.1:8742**).
- Exposes **`restart_sidecar`** — stops the tracked uvicorn child and spawns a fresh one (see `src-tauri/src/lib.rs`).

## Dev vs release builds

| Mode | Uvicorn bind host (implementation detail) | API URL returned to UI |
| ---- | ----------------------------------------- | ------------------------ |
| **Debug** (`tauri dev`) | `0.0.0.0` on API port (IPv4 all interfaces) | `http://127.0.0.1:{port}` |
| **Release** | `127.0.0.1` | `http://127.0.0.1:{port}` |

Binding `0.0.0.0` in dev avoids some **localhost vs 127.0.0.1** / IPv6 edge cases while still being local-only.

## Ports

| Port | Service |
| ---- | ------- |
| **5173** | Vite dev server (`strictPort: true` in `vite.config.ts`) |
| **8742** (default) | FastAPI — `SHADOW_API_PORT` / `FRAUD_COPILOT_API_PORT` |

If **5173** or **8742** is already taken, the stack may fail to start or the sidecar may fail to bind. Free the port or change `SHADOW_API_PORT` consistently (env + restart).

## Header controls

- **Sidecar** / **Ollama** dots — driven by periodic `/health` checks (`src/hooks/useHealthQuery.ts` via React Query).
- **Restart API** — invokes `restart_sidecar` (desktop only). Use when chat shows “could not reach” but you want to avoid terminal restarts.
- **Recheck health** — manual `/health` refresh.
- **Change model** — updates `.data/preferences.json`.

## Browser-only dev

If you open **http://localhost:5173** in Chrome/Safari **without** running Uvicorn:

- The UI will show API errors — there is **no** embedded sidecar in the browser.
- **Restart API** is not available (requires Tauri `invoke`).

Use **`npm run tauri:dev`** or run **uvicorn** manually and set **`VITE_API_BASE`**.

## Build commands

```bash
npm run tauri:dev      # dev window + vite + sidecar
npm run tauri:build    # release binary (runs `npm run build` first via Tauri config)
npm run desktop:build  # web build + tauri build one shot
```

## Resources

Tauri bundles **`../backend`** and **`resources/`** per `tauri.conf.json` for packaged builds—ensure Python packaging matches your release strategy.
