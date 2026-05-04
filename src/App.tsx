import { toast } from 'sonner'
import { useShadowStore } from './stores/shadowStore'
import { ThreePaneLayout } from './components/layout/ThreePaneLayout'
import { GhostButton, HealthPulsingDot } from './components/ui/ForensicChrome'
import { ForensicModal } from './components/ui/ForensicModal'
import { useHealthQuery } from './hooks/useHealthQuery'
import { fetchHealth, fetchOllamaModelTags, patchLlmPreferences, restartShadowSidecar } from './lib/api'
import type { CaseOut } from './lib/types'
import { useState } from 'react'

import { CommandPalette } from './components/ui/CommandPalette'

function formatApiError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e)
  let detail: string | null = null
  try {
    const j = JSON.parse(raw) as { detail?: string }
    if (typeof j.detail === 'string') detail = j.detail
  } catch {
    /* keep raw */
  }
  const base = detail ?? raw
  if (base.toLowerCase().includes('not found')) {
    return `${base} — Rebuild or hard-refresh the UI, restart the Python sidecar, and confirm the API base (header) points at this Shadow instance.`
  }
  return base
}

export default function App() {
  const [activeCase, setActiveCase] = useState<CaseOut | null>(null)
  const [review, setReview] = useState<{
    original: string
    suggested: string
    notes: string
  } | null>(null)
  const { apiBase, health, refresh } = useHealthQuery()
  const llm = useShadowStore((s) => s.llm)
  const setLlm = useShadowStore((s) => s.setLlm)

  const onRestartApi = () => {
    setLlm({ apiRestartBusy: true })
    const promise = restartShadowSidecar().then(async (msg) => {
      await refresh()
      return msg
    })
    toast.promise(promise, {
      loading: 'Restarting API...',
      success: (msg) => msg,
      error: (e) => (e instanceof Error ? e.message : String(e)),
    })
    promise.finally(() => setLlm({ apiRestartBusy: false }))
  }

  const openLlmSettings = () => {
    setLlm({
      err: null,
      ollamaTagsHint: null,
      ollamaTags: [],
      open: true,
    })
    void (async () => {
      try {
        const h = await fetchHealth()
        setLlm({
          draft: h.ollama_model ?? '',
          envDefault: h.ollama_env_default ?? h.ollama_model ?? '—',
          usingOverride: Boolean(h.ollama_using_override),
          err: null,
        })
      } catch (e) {
        setLlm({
          err: formatApiError(e),
          draft: health?.ollama_model ?? '',
          envDefault: health?.ollama_env_default ?? '—',
          usingOverride: Boolean(health?.ollama_using_override),
        })
      }
      try {
        const tags = await fetchOllamaModelTags()
        setLlm({
          ollamaTags: tags.models ?? [],
          ollamaTagsHint: tags.error
            ? `Could not list models from Ollama: ${tags.error}. Type a tag manually (same as \`ollama list\`).`
            : null,
        })
      } catch {
        setLlm({
          ollamaTags: [],
          ollamaTagsHint:
            'Installed-model picker unavailable (sidecar may need an update, or /ollama-models returned an error). Type a tag manually.',
        })
      }
    })()
  }

  return (
    <div className="flex h-screen min-h-0 flex-col bg-[#0d0d0d] text-zinc-100 antialiased">
      <CommandPalette />
      <header className="relative flex h-12 shrink-0 items-center gap-6 border-b border-zinc-800/95 bg-[#0c0c0f]/95 px-4 backdrop-blur-md before:pointer-events-none before:absolute before:inset-0 before:bg-[linear-gradient(90deg,transparent,rgba(139,92,246,0.04)_45%,transparent)] before:content-['']">
        <div className="relative flex min-w-0 flex-col leading-tight">
          <div className="flex items-center gap-2">
            <span className="font-semibold tracking-tight text-zinc-50">Shadow</span>
            <span className="rounded border border-emerald-500/35 bg-emerald-500/10 px-1.5 py-px font-mono text-[9px] font-semibold uppercase tracking-widest text-emerald-400/95">
              Local
            </span>
          </div>
          <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-zinc-600">Operations console</span>
        </div>
        <div className="hidden h-4 w-px shrink-0 bg-zinc-800 sm:block" aria-hidden />
        <div className="flex flex-1 flex-wrap items-center gap-4 text-[11px] text-zinc-500">
          <HealthPulsingDot ok={health?.ok ?? false} label="Sidecar" />
          <div className="flex items-center gap-1.5">
            <HealthPulsingDot ok={health?.ollama_reachable ?? false} label="Ollama" />
            <button
              type="button"
              className="max-w-[min(220px,40vw)] truncate font-mono text-[10px] text-zinc-500 hover:text-zinc-300 hover:underline decoration-zinc-600 underline-offset-2"
              title="Change model used for chat and tools"
              onClick={() => openLlmSettings()}
            >
              {health?.ollama_model ?? 'set model'}
            </button>
          </div>
          <span className="hidden font-mono text-[10px] text-zinc-600 sm:inline" title="API (loopback only)">
            {apiBase ?? '…'}
          </span>
        </div>
        <div className="relative ml-auto flex shrink-0 flex-wrap items-center justify-end gap-2">
          <GhostButton
            onClick={() => onRestartApi()}
            disabled={llm.apiRestartBusy}
            className="!py-1 text-[11px]"
            title="Stop and restart the bundled Python API (same port)"
          >
            {llm.apiRestartBusy ? 'Restarting…' : 'Restart API'}
          </GhostButton>
          <GhostButton onClick={() => openLlmSettings()} className="!py-1 text-[11px]">
            Change model
          </GhostButton>
          <GhostButton onClick={() => void refresh()} className="!py-1 text-[11px]">
            Recheck health
          </GhostButton>
        </div>
      </header>
      <ForensicModal open={llm.open} onClose={() => setLlm({ open: false })} title="Change Ollama model">
        <div className="mb-4 rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-xs text-violet-200">
          <span className="font-semibold">Recommendation:</span> For optimal agentic reasoning and tool use, we recommend using <strong>qwen2.5:32b</strong> (if you have the RAM) or <strong>llama3.1:8b-instruct-fp16</strong>.
        </div>
        <p className="text-xs leading-relaxed text-zinc-400">
          Pick or type the exact model tag Shadow should use for chat and tools (must exist in your local Ollama). This
          is saved under <span className="font-mono text-zinc-500">.data/preferences.json</span> and overrides{' '}
          <span className="font-mono text-zinc-500">SHADOW_OLLAMA_MODEL</span> from <span className="font-mono text-zinc-500">.env</span>{' '}
          until you revert below.
        </p>
        <p className="mt-2 text-[11px] text-zinc-500">
          <span className="text-zinc-600">.env default:</span>{' '}
          <span className="font-mono text-zinc-400">{llm.envDefault || '…'}</span>
          {llm.usingOverride ? (
            <span className="ml-2 text-amber-500/90">· using saved override</span>
          ) : (
            <span className="ml-2 text-zinc-600">· using .env default</span>
          )}
        </p>
        {llm.ollamaTagsHint ? <p className="mt-2 text-[11px] leading-snug text-amber-500/90">{llm.ollamaTagsHint}</p> : null}
        {llm.err ? <p className="mt-2 text-xs text-red-400">{llm.err}</p> : null}
        <label className="mt-3 block text-[10px] font-medium uppercase tracking-wider text-zinc-500">
          Model tag
          <input
            className="mt-1 w-full rounded-md border border-zinc-800 bg-zinc-950/80 px-2.5 py-2 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-violet-500/45 focus:outline-none"
            value={llm.draft}
            onChange={(e) => setLlm({ draft: e.target.value })}
            list="shadow-ollama-model-datalist"
            placeholder="Type or pick from your installed models"
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <datalist id="shadow-ollama-model-datalist">
          {llm.ollamaTags.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={llm.busy || !llm.draft.trim()}
            className="rounded-lg border border-emerald-500/45 bg-emerald-950/35 px-3 py-1.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-900/40 disabled:opacity-40"
            onClick={() => {
              setLlm({ busy: true, err: null })
              const promise = patchLlmPreferences({ ollama_model: llm.draft.trim() }).then(async () => {
                await refresh()
                setLlm({ open: false, busy: false })
              })
              toast.promise(promise, {
                loading: 'Saving model preference...',
                success: 'Model updated successfully',
                error: (e) => {
                  setLlm({ err: formatApiError(e), busy: false })
                  return 'Failed to update model'
                },
              })
            }}
          >
            {llm.busy ? 'Saving…' : 'Use this model'}
          </button>
          <button
            type="button"
            disabled={llm.busy || !llm.usingOverride}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
            onClick={() => {
              setLlm({ busy: true, err: null })
              const promise = patchLlmPreferences({ ollama_model: null }).then(async () => {
                await refresh()
                setLlm({ open: false, busy: false })
              })
              toast.promise(promise, {
                loading: 'Reverting model preference...',
                success: 'Reverted to .env default',
                error: (e) => {
                  setLlm({ err: formatApiError(e), busy: false })
                  return 'Failed to revert model'
                },
              })
            }}
          >
            Revert to .env default
          </button>
        </div>
      </ForensicModal>
      <main className="min-h-0 flex-1 min-w-0">
        <ThreePaneLayout
          activeCase={activeCase}
          setActiveCase={setActiveCase}
          review={review}
          setReview={setReview}
        />
      </main>
    </div>
  )
}
