import { AnimatePresence, motion } from 'framer-motion'
import { Code2, Pin, Search, Sparkles, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AuditLogOut, LeadOut, LeadWorkflowStatus } from '../../lib/types'
import { AGENT_INJECT_EVENT } from '../../lib/api'
import { useEvidenceBoard } from '../../hooks/useEvidenceBoard'

type Props = {
  caseId: string | null
}

function auditVisualKind(a: AuditLogOut): 'code' | 'search' | 'generic' {
  const code = a.code_executed?.trim() ?? ''
  if (code && /^\s*(with|select)\b/i.test(code)) return 'search'
  if (code) return 'code'
  if (/sql|query|duckdb|select/i.test(a.action_taken)) return 'search'
  return 'generic'
}

function AuditIcon({ kind }: { kind: 'code' | 'search' | 'generic' }) {
  const cls = 'h-4 w-4'
  if (kind === 'code') return <Code2 className={cls} aria-hidden />
  if (kind === 'search') return <Search className={cls} aria-hidden />
  return <Sparkles className={cls} aria-hidden />
}

function formatAuditTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function splitTitleDescription(desc: string): { title: string; body: string } {
  const lines = desc
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length >= 2) {
    return { title: lines[0]!, body: lines.slice(1).join(' ') }
  }
  if (desc.length <= 72) return { title: desc, body: '' }
  return { title: `${desc.slice(0, 72)}…`, body: desc.slice(72).trim() }
}

function JsonSyntax({ json }: { json: string }) {
  const parts = json.split(/("(?:[^"\\]|\\.)*")|(\btrue\b|\bfalse\b|\bnull\b)|(-?\d+\.?\d*(?:e[+-]?\d+)?)/gi)
  return (
    <code className="block whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed">
      {parts.map((t, i) => {
        if (!t) return null
        if (t.startsWith('"')) {
          return (
            <span key={i} className="text-emerald-400/90">
              {t}
            </span>
          )
        }
        if (/^(true|false|null)$/i.test(t)) {
          return (
            <span key={i} className="text-violet-400/85">
              {t}
            </span>
          )
        }
        if (/^-?\d/.test(t)) {
          return (
            <span key={i} className="text-amber-300/90">
              {t}
            </span>
          )
        }
        return (
          <span key={i} className="text-zinc-500">
            {t}
          </span>
        )
      })}
    </code>
  )
}

function severityTone(score: number): 'high' | 'med' | 'low' {
  if (score >= 0.65) return 'high'
  if (score >= 0.35) return 'med'
  return 'low'
}

function LeadCard({
  lead,
  busy,
  onAction,
  highlight,
}: {
  lead: LeadOut
  busy: boolean
  onAction: (id: string, s: LeadWorkflowStatus) => void
  highlight?: boolean
}) {
  const st = lead.status.toUpperCase() as LeadWorkflowStatus | string
  const { title, body } = splitTitleDescription(lead.description || 'Unspecified pattern')
  const sev = severityTone(lead.severity_score)
  const barColor =
    sev === 'high' ? 'bg-rose-500 shadow-[0_0_12px_rgba(244,63,94,0.35)]' : sev === 'med' ? 'bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.25)]' : 'bg-zinc-600'
  const jsonRaw = lead.raw_data_ref ? JSON.stringify(lead.raw_data_ref, null, 2) : null
  const verified = st === 'VERIFIED'
  const dismissed = st === 'DISMISSED'
  const escalated = st === 'ESCALATED'

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: highlight ? 14 : 6, scale: highlight ? 0.93 : 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{
        type: 'spring',
        stiffness: highlight ? 520 : 400,
        damping: highlight ? 26 : 30,
      }}
      className={`relative min-h-[9rem] overflow-hidden rounded-lg border bg-zinc-900 pl-3 pr-2.5 pt-2.5 pb-2 transition-shadow ${
        verified
          ? 'border-amber-500/35 ring-1 ring-amber-500/25 shadow-[inset_0_1px_0_rgba(245,158,11,0.12),0_4px_24px_rgba(0,0,0,0.35)]'
          : escalated
            ? 'border-rose-500/35'
            : 'border-zinc-800/90'
      } ${dismissed ? 'opacity-55' : ''} ${highlight ? 'ring-1 ring-fuchsia-500/30 shadow-[0_0_28px_rgba(168,85,247,0.12)]' : ''}`}
    >
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-r ${barColor}`} aria-hidden />
      {verified ? (
        <div className="absolute right-2 top-2 flex items-center gap-0.5 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-200/95">
          <Pin className="h-3 w-3" strokeWidth={2.5} aria-hidden />
          Verified
        </div>
      ) : null}
      <div className="pl-1.5">
        <div className="flex items-start justify-between gap-2 pr-14">
          <h3 className="text-[12px] font-semibold leading-snug tracking-tight text-zinc-100">{title}</h3>
          <span className="shrink-0 font-mono text-[9px] text-zinc-500">{lead.severity_score.toFixed(2)}</span>
        </div>
        {body ? <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">{body}</p> : null}
        <div className="mt-2 rounded border border-zinc-800/80 bg-zinc-950/80 p-2">
          <div className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-zinc-600">Evidence snippet</div>
          {jsonRaw ? (
            <div className="max-h-28 overflow-auto rounded border border-zinc-800/60 bg-[#0c0c0e] px-2 py-1.5">
              <JsonSyntax json={jsonRaw} />
            </div>
          ) : (
            <span className="font-mono text-[10px] text-zinc-600">No raw row reference.</span>
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              window.dispatchEvent(
                new CustomEvent(AGENT_INJECT_EVENT, {
                  detail: {
                    text: `/system: Perform a deep dive on Lead #${lead.id}. Analyze related transactions in the last 48 hours.`,
                  },
                }),
              )
            }}
            className="rounded border border-fuchsia-500/40 bg-fuchsia-500/10 px-2 py-1 text-[10px] font-medium text-fuchsia-200/95 transition-colors enabled:hover:border-fuchsia-400/55 enabled:hover:bg-fuchsia-500/15 disabled:opacity-40"
          >
            Request Deep Dive
          </button>
          <button
            type="button"
            disabled={busy || dismissed}
            onClick={() => onAction(lead.id, 'DISMISSED')}
            className="rounded border border-zinc-700/80 bg-zinc-950/80 px-2 py-1 text-[10px] font-medium text-zinc-400 transition-colors enabled:hover:border-zinc-600 enabled:hover:text-zinc-200 disabled:opacity-40"
          >
            Dismiss
          </button>
          <button
            type="button"
            disabled={busy || verified}
            onClick={() => onAction(lead.id, 'VERIFIED')}
            className="rounded border border-amber-500/35 bg-amber-500/10 px-2 py-1 text-[10px] font-medium text-amber-200/90 transition-colors enabled:hover:border-amber-400/50 disabled:opacity-40"
          >
            Verify
          </button>
          <button
            type="button"
            disabled={busy || escalated}
            onClick={() => onAction(lead.id, 'ESCALATED')}
            className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[10px] font-medium text-rose-200/90 transition-colors enabled:hover:border-rose-400/55 disabled:opacity-40"
          >
            Escalate
          </button>
        </div>
      </div>
    </motion.article>
  )
}

export function EvidenceBoard({ caseId }: Props) {
  const { data, loading, err, patchLeadStatus, freshLeadIds } = useEvidenceBoard(caseId, { pollMs: 12000 })
  const [pop, setPop] = useState<{ audit: AuditLogOut; x: number; y: number } | null>(null)
  const [acting, setActing] = useState(false)
  const popRef = useRef<HTMLDivElement>(null)

  const timeline = useMemo(() => {
    const list = data?.audit_logs ?? []
    if (list.length === 0) return null
    return (
      <div className="relative min-h-[120px] px-3 pb-2 pt-6">
        <div
          className="pointer-events-none absolute left-8 right-4 top-[52px] h-px bg-gradient-to-r from-zinc-700/20 via-zinc-600/80 to-zinc-700/20"
          aria-hidden
        />
        <div className="flex min-h-[72px] gap-3 overflow-x-auto overflow-y-visible pb-4 pl-2 pr-2 pt-1 [scrollbar-width:thin]">
          {list.map((a, i) => {
            const kind = auditVisualKind(a)
            return (
              <motion.div
                key={a.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.04, 0.5), type: 'spring', stiffness: 420, damping: 28 }}
                className="relative flex shrink-0 flex-col items-center"
              >
                <span className="mb-1 font-mono text-[9px] text-zinc-600">{formatAuditTime(a.timestamp)}</span>
                <motion.button
                  type="button"
                  whileHover={{ scale: 1.06 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={(e) => {
                    const r = (e.currentTarget as HTMLButtonElement).getBoundingClientRect()
                    setPop({ audit: a, x: r.left + r.width / 2, y: r.bottom + 6 })
                  }}
                  className={`relative z-10 flex h-10 w-10 items-center justify-center rounded-full border text-zinc-200 shadow-lg transition-colors ${
                    kind === 'code'
                      ? 'border-violet-500/40 bg-violet-500/15 text-violet-200'
                      : kind === 'search'
                        ? 'border-cyan-500/40 bg-cyan-500/15 text-cyan-200'
                        : 'border-zinc-600 bg-zinc-800 text-zinc-300'
                  } `}
                  aria-label={`Audit event ${a.id}`}
                >
                  <AuditIcon kind={kind} />
                </motion.button>
              </motion.div>
            )
          })}
        </div>
      </div>
    )
  }, [data?.audit_logs])

  const closePop = useCallback(() => setPop(null), [])

  useEffect(() => {
    if (!pop) return
    const onDoc = (e: MouseEvent) => {
      const el = popRef.current
      if (el && e.target instanceof Node && !el.contains(e.target)) closePop()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePop()
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [pop, closePop])

  const onLeadAction = async (id: string, s: LeadWorkflowStatus) => {
    setActing(true)
    try {
      await patchLeadStatus(id, s)
    } finally {
      setActing(false)
    }
  }

  const auditCount = data?.audit_logs?.length ?? 0

  if (!caseId) {
    return (
      <div className="flex h-full min-h-[240px] items-center justify-center border border-dashed border-zinc-800 bg-zinc-900 px-4 font-mono text-[11px] text-zinc-600">
        Activate a case to open the evidence board.
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-zinc-900 text-zinc-200">
      {err ? (
        <div className="border-b border-rose-500/25 bg-rose-950/40 px-3 py-2 font-mono text-[11px] text-rose-300/90">{err}</div>
      ) : null}

      <div className="flex min-h-0 flex-[0_0_44%] max-h-[46%] flex-col border-b border-zinc-800/90">
        <div className="flex items-center justify-between px-3 py-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">Audit timeline</span>
          {loading && !data ? <span className="font-mono text-[10px] text-zinc-600">Syncing…</span> : null}
        </div>
        <div className="min-h-0 flex-1 overflow-y-hidden overflow-x-hidden">
          {auditCount === 0 ? (
            <div className="flex h-full items-center justify-center px-4 font-mono text-[11px] text-zinc-600">
              No audit events yet — sandbox runs and agent queries appear here.
            </div>
          ) : (
            timeline
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
        <div className="flex shrink-0 items-center justify-between px-3 pt-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">Signal grid · leads</span>
          {loading && data ? <span className="font-mono text-[9px] text-zinc-600">Polling…</span> : null}
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-3 pb-3">
          {!data?.leads?.length ? (
            <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-950/30 py-10 text-center font-mono text-[11px] text-zinc-600">
              No leads indexed for this case.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
              {data.leads.map((lead) => (
                <LeadCard key={lead.id} lead={lead} busy={acting} highlight={freshLeadIds.has(lead.id)} onAction={onLeadAction} />
              ))}
            </div>
          )}
        </div>
      </div>

      <AnimatePresence>
        {pop ? (
          <motion.div
            key={pop.audit.id}
            ref={popRef}
            role="dialog"
            aria-modal="true"
            initial={{ opacity: 0, y: -6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 480, damping: 32 }}
            className="fixed z-[80] w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 rounded-lg border border-zinc-700/90 bg-zinc-900/98 p-3 shadow-[0_20px_50px_rgba(0,0,0,0.55)] backdrop-blur-md"
            style={{ left: Math.min(Math.max(pop.x, 160), typeof window !== 'undefined' ? window.innerWidth - 160 : 9999), top: pop.y }}
          >
            <div className="mb-2 flex items-start justify-between gap-2 border-b border-zinc-800 pb-2">
              <div>
                <div className="font-mono text-[9px] uppercase tracking-wider text-zinc-500">{formatAuditTime(pop.audit.timestamp)}</div>
                <p className="mt-1 text-[12px] font-medium leading-snug text-zinc-100">{pop.audit.action_taken}</p>
              </div>
              <button
                type="button"
                onClick={closePop}
                className="rounded p-1 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {pop.audit.agent_notes ? (
              <p className="mb-2 rounded border border-zinc-800/80 bg-zinc-950/60 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-emerald-300/85">
                {pop.audit.agent_notes}
              </p>
            ) : null}
            {pop.audit.code_executed ? (
              <div>
                <div className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-zinc-600">Payload</div>
                <pre className="max-h-40 overflow-auto rounded border border-zinc-800/80 bg-[#0a0a0c] p-2 font-mono text-[10px] leading-snug text-zinc-400">
                  {pop.audit.code_executed}
                </pre>
              </div>
            ) : (
              <p className="font-mono text-[10px] text-zinc-600">No code or query text recorded.</p>
            )}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
