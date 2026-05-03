import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8742'
  const wsTarget = proxyTarget.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
  const devPort = Number(env.VITE_DEV_PORT || env.PORT || 5173)

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: devPort,
      strictPort: true,
      // Browser dev: default 5173. Tauri uses `npm run dev:tauri` (VITE_DEV_PORT=1420) — see tauri.conf.json.
      open: false,
      // Dev: browser + Tauri webview call same-origin `/api/*` etc.; Vite forwards to the Python sidecar.
      // Run uvicorn on 8742 (or set VITE_PROXY_TARGET). See docs/TROUBLESHOOTING.md.
      proxy: {
        '/api': { target: proxyTarget, changeOrigin: true },
        '/health': { target: proxyTarget, changeOrigin: true },
        '/llm-preferences': { target: proxyTarget, changeOrigin: true },
        '/ollama-models': { target: proxyTarget, changeOrigin: true },
        '/ws': { target: wsTarget, ws: true },
      },
    },
  }
})
