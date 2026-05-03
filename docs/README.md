# Shadow documentation

This folder holds deeper guides for the **Shadow** repository (local-first fraud / disputes operations console). The root **[README.md](../README.md)** is the main entry point; use the links below for topic-specific detail.

| Document | Description |
| -------- | ----------- |
| [GETTING_STARTED.md](./GETTING_STARTED.md) | First-time setup, verify install, first case |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Layers, data flow, agent graph, key packages |
| [CONFIGURATION.md](./CONFIGURATION.md) | Environment variables, paths, model overrides |
| [API.md](./API.md) | HTTP / WebSocket surface; how to use OpenAPI |
| [AGENT.md](./AGENT.md) | LangGraph agent, personas, tools, chat contract |
| [TAURI_DESKTOP.md](./TAURI_DESKTOP.md) | Desktop shell, sidecar lifecycle, Restart API, ports |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | Common failures (API down, Ollama, ports, imports) |

Additional context used by specific personas lives under `backend/agents/` (e.g. playbook markdown).
