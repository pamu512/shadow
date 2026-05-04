# Getting started

## 1. Prerequisites

| Tool | Why |
| ---- | --- |
| **Node.js** (current LTS) | Vite, frontend build, Tauri CLI |
| **Python 3.11+** | FastAPI sidecar (`pyproject.toml`: `requires-python`) |
| **Rust + platform deps** | Only if you use **Tauri** (`npm run tauri:dev` / `tauri:build`) |
| **Ollama** (recommended) | Local LLM at `http://localhost:11434/v1` for chat and tools |

## 2. Clone and install (frontend)

```bash
git clone <repository-url> shadow
cd shadow
npm install
```

## 3. Python environment (backend package)

Always work from the **repository root** so the `backend` package resolves.

```bash
python3.11 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
# or: uv pip install -e .
```

### Optional: tool-confidence ONNX bundle

For faster, non-LLM **tool output confidence** scores (used when `SHADOW_LLM_TOOL_CONFIDENCE` is `false`), generate the default model artifact:

```bash
python -m backend.agent.train_confidence_model
```

That writes **`<repo>/.data/tool_confidence.onnx`** (same directory family as `SHADOW_DATA_DIR`). Skip this step if you are fine with heuristic-only scoring until you train your own model.

## 4. Choose how you run the stack

### Option A — Full desktop (recommended for daily use)

Starts Vite, the Rust shell, and spawns the Python API on the configured port.

```bash
npm run tauri:dev
```

Use the **Shadow** window that opens. The header shows **Sidecar** / **Ollama** health; **Restart API** restarts the bundled uvicorn without using a terminal.

### Option B — Web UI + manual API (two terminals)

**Terminal 1 — API**

```bash
cd shadow
export PYTHONPATH="$(pwd)"
source .venv/bin/activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8742
```

**Terminal 2 — Vite**

```bash
cd shadow
npm run dev
```

Open **http://localhost:5173**. Set **`VITE_API_BASE=http://127.0.0.1:8742`** if the UI cannot reach the API (see [CONFIGURATION.md](./CONFIGURATION.md)).

> **Note:** Chat and most features require the API. A browser tab on **5173** alone does **not** start Python.

## 5. Verify

- **API:** [http://127.0.0.1:8742/docs](http://127.0.0.1:8742/docs) (OpenAPI)
- **Health:** `curl -s http://127.0.0.1:8742/health` → JSON with `ok`, `ollama_model`, etc.

## 6. First case

1. In the UI, create a **New case** and upload a **`.csv`** file.
2. Activate the case if prompted.
3. Open the **Agent Console**, pick a **persona** (e.g. General Fraud Analyst), and send a message.

See [AGENT.md](./AGENT.md) for how chat and tools behave.
