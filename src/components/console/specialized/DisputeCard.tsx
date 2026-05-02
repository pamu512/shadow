import { useCallback, useRef } from 'react'

function evidenceLineStatus(status: string): 'ok' | 'bad' | 'mid' {
  const s = status.toLowerCase()
  if (s.includes('found') || s.includes('strong') || s.includes('pass') || s.includes('scanned') || s.includes('present'))
    return 'ok'
  if (s.includes('missing') || s.includes('weak') || s.includes('fail') || s.includes('gap')) return 'bad'
  return 'mid'
}

export function DisputeCard({
  payload,
  layout = 'letter',
}: {
  payload: Record<string, unknown>
  layout?: 'letter' | 'evidence_checklist'
}) {
  const printRef = useRef<HTMLDivElement>(null)
  const score = typeof payload.chargeback_risk_score === 'number' ? payload.chargeback_risk_score : null
  const winPct =
    typeof payload.win_probability_percent === 'number'
      ? payload.win_probability_percent
      : typeof payload.win_probability === 'number'
        ? Math.round(Number(payload.win_probability) * 1000) / 10
        : null
  const summary = Array.isArray(payload.executive_summary) ? (payload.executive_summary as string[]) : []
  const hunt = Array.isArray(payload.key_evidence_hunt) ? (payload.key_evidence_hunt as Record<string, unknown>[]) : []

  const onPrint = useCallback(() => {
    const w = window.open('', '_blank', 'width=720,height=900')
    if (!w) return
    const body = printRef.current?.innerHTML ?? ''
    w.document.write(
      `<!DOCTYPE html><html><head><title>Representment summary</title><style>body{font-family:ui-monospace,monospace;padding:24px;background:#fff;color:#111;}h1{font-size:18px;}p{margin:8px 0;line-height:1.5;}</style></head><body>${body}</body></html>`,
    )
    w.document.close()
    w.focus()
    w.print()
    w.close()
  }, [])

  const checklist =
    layout === 'evidence_checklist' ? (
      <div className="rounded-md border border-zinc-800/60 bg-[#0a0a0c] p-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-emerald-400/90">
          Representment evidence · chargeback expert
        </p>
        <p className="mb-3 text-[9px] text-zinc-500">IP logs, POD, and policy artifacts — green = present, red = missing or weak.</p>
        {hunt.length === 0 ? (
          <p className="text-[10px] text-zinc-600">No structured checklist in payload — run analyze_chargeback_risk_tool.</p>
        ) : (
          <ul className="space-y-2">
            {hunt.map((h, i) => {
              const label = String(h.evidence_type ?? 'Evidence item')
              const st = String(h.status ?? '')
              const tier = evidenceLineStatus(st)
              const dot =
                tier === 'ok'
                  ? 'bg-emerald-500 shadow-[0_0_10px_rgba(52,211,153,0.5)]'
                  : tier === 'bad'
                    ? 'bg-red-500 shadow-[0_0_10px_rgba(248,113,113,0.45)]'
                    : 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.35)]'
              return (
                <li key={i} className="flex gap-2 rounded border border-zinc-800/80 bg-zinc-950/50 px-2 py-2">
                  <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-medium text-zinc-200">{label}</div>
                    <div className="text-[10px] text-zinc-500">{st || '—'}</div>
                    {h.why ? <div className="mt-0.5 text-[9px] text-zinc-600">{String(h.why)}</div> : null}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    ) : null

  return (
    <div className="mt-1.5 w-full max-w-full space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/80 p-3 font-mono shadow-[0_0_28px_rgba(168,85,247,0.1)] backdrop-blur-md">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-zinc-800/80 pb-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">Chargeback desk</div>
          <div className="text-xs font-semibold text-zinc-100">
            {layout === 'evidence_checklist' ? 'Evidence checklist' : 'Representment letter preview'}
          </div>
        </div>
        <button
          type="button"
          onClick={onPrint}
          className="shrink-0 rounded-lg border border-violet-500/45 bg-violet-950/40 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wide text-violet-100 hover:border-violet-400/60"
        >
          Print PDF
        </button>
      </div>

      {checklist}

      <div ref={printRef} className="space-y-3 rounded-md border border-zinc-800/60 bg-[#0a0a0c] p-3 text-[11px] leading-relaxed text-zinc-300">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Merchant / issuer summary</p>
        {score != null ? (
          <p>
            <span className="text-zinc-500">Evidence strength index:</span>{' '}
            <span className="text-lg font-bold text-fuchsia-300">{score}</span>
            <span className="text-zinc-600"> / 100</span>
          </p>
        ) : null}
        {winPct != null ? (
          <p>
            <span className="text-zinc-500">Heuristic win probability:</span>{' '}
            <span className="font-semibold text-emerald-300/90">{winPct}%</span>
          </p>
        ) : null}
        {summary.length > 0 ? (
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase text-zinc-600">Executive narrative</p>
            <ul className="list-inside list-disc space-y-1 text-zinc-400">
              {summary.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {hunt.length > 0 ? (
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase text-zinc-600">Evidence checklist</p>
            <ul className="space-y-1.5">
              {hunt.map((h, i) => (
                <li key={i} className="rounded border border-zinc-800/80 bg-zinc-950/50 px-2 py-1.5">
                  <span className="text-zinc-200">{String(h.evidence_type ?? 'Item')}</span>
                  <span className="mx-1 text-zinc-600">·</span>
                  <span className="text-zinc-500">{String(h.status ?? '')}</span>
                  {h.why ? <div className="mt-0.5 text-[10px] text-zinc-600">{String(h.why)}</div> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="border-t border-zinc-800 pt-2 text-[9px] text-zinc-600">
          Draft for operator review — not legal advice. Attach issuer-specific exhibits before filing.
        </p>
      </div>
    </div>
  )
}
