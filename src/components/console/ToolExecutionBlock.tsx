import { useMemo, useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronRight, Pin, XCircle } from 'lucide-react'
import { isBotClusterWorkspacePayload, useOptionalWorkspaceData } from '../../context/WorkspaceDataContext'
import { getComponentForOutput, getOutputKind } from './SpecializedOutputRenderer'
import type { ForensicTag } from './terminalMessageUtils'
import { ToolVerdictRibbon } from './ToolVerdictRibbon'
import type { PinnedForensicPayload } from './ForensicResultTranscriptCard'

export type ParsedToolMessage = {
  toolName: string
  payload: Record<string, unknown>
  rawBody: string
}

export function parseToolMessageContent(content: string): ParsedToolMessage | null {
  const trimmed = content.trim()
  const m = trimmed.match(/^\[tool\s+([^\]]+)\]\s*([\s\S]*)$/i)
  if (m) {
    const toolName = m[1].trim()
    const body = m[2].trim()
    if (!body) return null
    try {
      const parsed: unknown = JSON.parse(body)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return null
      }
      return { toolName, payload: parsed as Record<string, unknown>, rawBody: body }
    } catch {
      return null
    }
  }
  return null
}

/** When the log line is raw JSON (no `[tool name]` prefix). Parsed only if `[EXECUTION]` prefix or UI tag EXECUTION. */
export function buildWorkbenchPinFromTool(toolName: string, payload: Record<string, unknown>): PinnedForensicPayload {
  const id = `pin-tool-${toolName}-${Date.now().toString(36)}`
  const hw = payload.hardware_ip_forensics as Record<string, unknown> | undefined
  let title = toolName.replace(/_tool$/i, '').replace(/_/g, ' ')
  let subtitle = 'Pinned tool output'
  if (hw && typeof hw === 'object') {
    const ua = Number(hw.unique_accounts_on_dominant)
    const di = Number(hw.unique_ips_on_dominant)
    if (Number.isFinite(ua) && Number.isFinite(di) && ua > 0 && di > 0) {
      const ratio = (ua / di).toFixed(2)
      title = `${ratio}:1 HW·TO·IP RATIO`
      subtitle = String(hw.verdict_label ?? hw.infrastructure_summary ?? 'Hardware vs IP forensic hit').slice(0, 220)
    }
  } else if (typeof payload.ato_risk_score === 'number') {
    title = `ATO risk ${Number(payload.ato_risk_score).toFixed(0)}`
    subtitle = String((payload.forensic_verdict as { headline?: string } | undefined)?.headline ?? subtitle).slice(
      0,
      220,
    )
  } else if (typeof payload.bot_density_pct === 'number') {
    title = `Bot density ${Number(payload.bot_density_pct).toFixed(1)}%`
  }
  return { id, title, subtitle, payload: { ...payload, _pinned_tool: toolName }, pinnedAt: Date.now() }
}

export function parseBareJsonExecutionPayload(content: string, tag: ForensicTag): ParsedToolMessage | null {
  const hadExecPrefix = /^\[EXECUTION\]/i.test(content.trim())
  const trimmed = content.trim().replace(/^\[EXECUTION\]\s*/i, '').trim()
  if (!trimmed.startsWith('{')) return null
  if (!hadExecPrefix && tag !== 'EXECUTION') return null
  try {
    const parsed: unknown = JSON.parse(trimmed)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return null
    }
    return { toolName: 'execution', payload: parsed as Record<string, unknown>, rawBody: trimmed }
  } catch {
    return null
  }
}

/** Pass `executionTag` when the line is tagged EXECUTION (e.g. tool output); avoids treating prose as JSON. */
export function isToolExecutionRenderable(content: string, executionTag: boolean): boolean {
  if (parseToolMessageContent(content)) return true
  const tag: ForensicTag = executionTag ? 'EXECUTION' : 'SYSTEM'
  return parseBareJsonExecutionPayload(content, tag) !== null
}

const SIGNAL_BADGE: Record<string, string> = {
  TIME_BURST: 'border-red-500/45 bg-red-950/50 text-red-200',
  SEQUENTIAL_ID_PATTERN: 'border-orange-500/40 bg-orange-950/45 text-orange-200',
  SHARED_SUBNET_UA: 'border-violet-500/40 bg-violet-950/45 text-violet-200',
  STALE_CHROME_UA: 'border-amber-500/40 bg-amber-950/45 text-amber-200',
  SHARED_SUBNET_CANVAS: 'border-cyan-500/40 bg-cyan-950/45 text-cyan-200',
  DISPOSABLE_EMAIL_DOMAIN: 'border-rose-500/40 bg-rose-950/45 text-rose-200',
  GMAIL_DOT_VARIANTS: 'border-fuchsia-500/40 bg-fuchsia-950/45 text-fuchsia-200',
  HIGH_ENTROPY_LOCAL: 'border-zinc-600 bg-zinc-900/80 text-zinc-300',
  INFRA_GEO_CONTEXT: 'border-slate-500/40 bg-slate-950/50 text-slate-200',
}

function signalBadgeClass(signal: string): string {
  return SIGNAL_BADGE[signal] ?? 'border-zinc-700 bg-zinc-900/70 text-zinc-300'
}

/** Hide huge Python tracebacks in the agent log; keep the first line + hint. */
function sanitizeToolErrorForUi(raw: string): string {
  if (!/traceback \(most recent call last\)/i.test(raw)) return raw
  const first = raw.split('\n')[0]?.trim() || 'Tool error'
  return `${first}\n… (full traceback hidden — check sidecar logs or retry with schema mapping.)`
}

function formatStatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(v)
  return String(v)
}

type ClusterRow = {
  cluster_id?: string
  cluster_type?: string
  size?: number
  signals?: unknown
}

function normalizeClusters(payload: Record<string, unknown>): ClusterRow[] {
  const raw = payload.clusters
  if (!Array.isArray(raw)) return []
  return raw.filter((c): c is ClusterRow => typeof c === 'object' && c !== null)
}

type Props = {
  toolName: string
  payload: Record<string, unknown>
  rawBody: string
  /** Ask the agent to re-run ATO with schema auto-mapping (empty user_id). */
  onRetryAtoAutoMap?: () => void
  onPinWorkbench?: (item: PinnedForensicPayload) => void
}

export function ToolExecutionBlock({ toolName, payload, rawBody, onRetryAtoAutoMap, onPinWorkbench }: Props) {
  const [rawOpen, setRawOpen] = useState(false)
  const workspace = useOptionalWorkspaceData()

  const ok = payload.ok !== false
  const outputKind = useMemo(() => getOutputKind(payload), [payload])
  const specialized = outputKind !== null
  const clusters = useMemo(() => normalizeClusters(payload), [payload])

  const refinedStats = useMemo(() => {
    const out: { label: string; value: string }[] = []
    const add = (label: string, key: string) => {
      if (key in payload) out.push({ label, value: formatStatValue(payload[key]) })
    }
    add('Rows', 'row_count')
    add('Bot density %', 'bot_density_pct')
    add('Unique users', 'unique_users')
    add('Max bot % (5m)', 'max_bot_pct_5m_window')
    if (clusters.length) out.push({ label: 'Clusters', value: String(clusters.length) })
    if ('high_bot_window_alert' in payload) {
      out.push({ label: 'High bot window', value: formatStatValue(payload.high_bot_window_alert) })
    }
    return out
  }, [payload, clusters.length])

  const errorMsg =
    typeof payload.error === 'string'
      ? payload.error
      : typeof payload.detail === 'string'
        ? payload.detail
        : null

  const tn = toolName.toLowerCase()
  const isAtoRiskTool = tn.includes('ato_risk')
  const atoRisk = typeof payload.ato_risk_score === 'number' ? Number(payload.ato_risk_score) : null
  const showAtoRetry = !ok && isAtoRiskTool && Boolean(onRetryAtoAutoMap)

  const canPin = Boolean(onPinWorkbench && ok && (specialized || refinedStats.length > 0 || clusters.length > 0))

  return (
    <div className="mt-1.5 w-full max-w-full overflow-hidden rounded-lg border border-zinc-800 bg-zinc-900/50 font-mono text-[11px] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
      <ToolVerdictRibbon
        toolName={toolName}
        payload={payload}
        ok={ok}
        rightSlot={
          canPin ? (
            <button
              type="button"
              title="Pin to right-rail Workbench"
              className="flex items-center gap-1 rounded-md border border-amber-500/45 bg-amber-950/40 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-100 hover:bg-amber-900/45"
              onClick={() => onPinWorkbench?.(buildWorkbenchPinFromTool(toolName, payload))}
            >
              <Pin className="h-3.5 w-3.5" aria-hidden />
              Pin
            </button>
          ) : null
        }
      />
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/90 bg-zinc-950/50 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          {ok ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden strokeWidth={2} />
          ) : (
            <XCircle className="h-4 w-4 shrink-0 text-red-400" aria-hidden strokeWidth={2} />
          )}
          <span className="font-semibold tracking-tight text-zinc-100">
            {ok ? 'Tool execution' : 'Something went wrong'}
          </span>
        </div>
        <span className="truncate rounded border border-zinc-800/80 bg-zinc-900/80 px-2 py-0.5 text-[10px] font-medium text-zinc-500">
          {toolName === 'json' || toolName === 'execution' ? 'structured output' : toolName}
        </span>
      </div>

      {!ok && errorMsg ? (
        <div className="border-b border-zinc-800/60 px-3 py-2 whitespace-pre-wrap font-sans text-[11px] leading-relaxed text-amber-200/90">
          {sanitizeToolErrorForUi(errorMsg)}
        </div>
      ) : null}

      {showAtoRetry ? (
        <div className="border-b border-zinc-800/60 px-3 py-2">
          <button
            type="button"
            className="w-full rounded-md border border-violet-500/45 bg-violet-950/40 px-3 py-2 text-left text-[11px] font-medium text-violet-100 transition-colors hover:bg-violet-900/35"
            onClick={() => onRetryAtoAutoMap?.()}
          >
            Retry with auto-mapping
            <span className="mt-0.5 block text-[10px] font-normal text-zinc-500">
              Sends a follow-up asking the agent to call ATO analysis with an empty user id so the server picks
              acc_id / user_id from your dataset.
            </span>
          </button>
        </div>
      ) : null}

      {isAtoRiskTool && atoRisk != null && !(specialized && outputKind === 'ato') ? (
        <div className="border-b border-zinc-800/60 px-3 py-2.5 font-sans">
          <div className="text-[10px] font-medium text-zinc-500">ATO risk score (0–100)</div>
          <div className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-zinc-800">
            <div
              className={`h-full rounded-full ${
                atoRisk >= 60
                  ? 'bg-gradient-to-r from-rose-600 to-red-500'
                  : atoRisk >= 35
                    ? 'bg-gradient-to-r from-amber-600 to-orange-500'
                    : 'bg-gradient-to-r from-emerald-700 to-emerald-500'
              }`}
              style={{ width: `${Math.min(100, Math.max(0, atoRisk))}%` }}
            />
          </div>
          <div className="mt-1 text-right text-xs font-semibold tabular-nums text-rose-200/95">{atoRisk.toFixed(1)}%</div>
        </div>
      ) : null}

      {specialized ? (
        <div className="border-b border-zinc-800/60 px-2 py-2">{getComponentForOutput(payload, toolName)}</div>
      ) : (
        <>
          {refinedStats.length > 0 ? (
            <div className="flex flex-wrap gap-x-4 gap-y-1 border-b border-zinc-800/60 px-3 py-2">
              {refinedStats.map((s) => (
                <div key={s.label} className="flex items-baseline gap-1.5">
                  <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">{s.label}</span>
                  <span className="text-zinc-200">{s.value}</span>
                </div>
              ))}
            </div>
          ) : null}

          {clusters.length > 0 ? (
            <div className="border-b border-zinc-800/60 px-3 py-2">
              <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Clusters</div>
              <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:thin]">
                {clusters.map((c, idx) => {
                  const id = String(c.cluster_id ?? `cluster_${idx}`)
                  const size = typeof c.size === 'number' ? c.size : '—'
                  const sigs = Array.isArray(c.signals) ? c.signals.filter((x): x is string => typeof x === 'string') : []
                  const ctype = typeof c.cluster_type === 'string' ? c.cluster_type : null
                  return (
                    <div
                      key={`${id}-${idx}`}
                      className="w-[min(220px,calc(100vw-4rem))] shrink-0 rounded-md border border-zinc-800 bg-zinc-950/40 p-2.5"
                    >
                      <div className="mb-1 truncate text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                        {id}
                      </div>
                      <div className="mb-2 text-zinc-200">
                        <span className="text-zinc-500">Size</span>{' '}
                        <span className="font-medium text-zinc-100">{size}</span>
                        {ctype ? (
                          <span className="ml-2 text-[10px] text-zinc-600">· {ctype.replace(/_/g, ' ')}</span>
                        ) : null}
                      </div>
                      {sigs.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {sigs.map((sig) => (
                            <span
                              key={sig}
                              className={`inline-block rounded border px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide ${signalBadgeClass(sig)}`}
                            >
                              {sig.replace(/_/g, ' ')}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          {workspace && ok && isBotClusterWorkspacePayload(payload) ? (
            <div className="border-b border-zinc-800/60 px-3 py-2.5">
              <button
                type="button"
                className="w-full rounded-lg border border-cyan-500/45 bg-gradient-to-r from-cyan-950/60 to-emerald-950/40 px-4 py-2.5 text-center text-[11px] font-bold uppercase tracking-[0.12em] text-cyan-100 shadow-[0_0_20px_rgba(6,182,212,0.15)] transition-all hover:border-cyan-400/60 hover:from-cyan-900/50 hover:to-emerald-900/35 hover:shadow-[0_0_28px_rgba(34,211,238,0.2)]"
                onClick={() => workspace.setActiveWorkspaceData({ ...payload })}
              >
                Send to Workspace ➔
              </button>
              <p className="mt-1.5 text-center text-[9px] font-medium uppercase tracking-wider text-zinc-600">
                Opens Bot Clusters tab with interactive table
              </p>
            </div>
          ) : null}
        </>
      )}

      <div className="px-2 py-1">
        <button
          type="button"
          onClick={() => setRawOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[10px] font-medium uppercase tracking-wider text-zinc-500 transition-colors hover:bg-zinc-800/50 hover:text-zinc-300"
        >
          {rawOpen ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
          )}
          View Raw Output
        </button>
        {rawOpen ? (
          <pre className="mb-2 max-h-64 overflow-auto rounded border border-zinc-800/80 bg-[#050507] p-2 text-[10px] leading-relaxed text-zinc-400">
            {rawBody}
          </pre>
        ) : null}
      </div>
    </div>
  )
}
