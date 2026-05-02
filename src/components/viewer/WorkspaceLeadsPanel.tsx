import type { LeadOut } from '../../lib/types'

function isHardwarePin(lead: LeadOut): boolean {
  const rd = lead.raw_data_ref
  return Boolean(rd && typeof rd === 'object' && (rd as { pin_kind?: string }).pin_kind === 'hardware_canvas')
}

type Props = {
  caseId: string | null
  leads: LeadOut[]
  loading: boolean
  err: string | null
  freshLeadIds: Set<string>
}

/** Evidence Board stream for the right-rail Active leads tab. */
export function WorkspaceLeadsPanel({ caseId, leads, loading, err, freshLeadIds }: Props) {
  const sorted = [...leads].sort((a, b) => {
    const ta = a.created_at ? Date.parse(a.created_at) : 0
    const tb = b.created_at ? Date.parse(b.created_at) : 0
    return tb - ta
  })

  if (!caseId) {
    return <p className="p-4 text-[11px] text-zinc-500">Select a case to load leads.</p>
  }

  return (
    <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3 [scrollbar-width:thin]">
      <div className="rounded-lg border border-zinc-800/90 bg-zinc-950/40 px-3 py-2">
        <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-cyan-500/90">Active leads</div>
        <p className="mt-1 text-[10px] leading-snug text-zinc-600">
          Live Evidence Board stream for this case. Hardware auto-pins may appear here.
        </p>
      </div>
      {loading && leads.length === 0 ? <p className="text-[10px] text-zinc-500">Loading…</p> : null}
      {err ? <p className="text-[10px] text-rose-400/90">{err}</p> : null}
      {sorted.length === 0 && !loading ? <p className="text-[10px] text-zinc-600">No leads yet.</p> : null}
      {sorted.map((lead) => {
        const pin = isHardwarePin(lead)
        const fresh = freshLeadIds.has(lead.id)
        const rd = (lead.raw_data_ref ?? {}) as { fingerprint_preview?: string }
        return (
          <div
            key={lead.id}
            className={`rounded-md border px-2.5 py-2 ${
              pin
                ? 'border-amber-500/45 bg-amber-950/35 shadow-[0_0_12px_rgba(245,158,11,0.12)]'
                : 'border-zinc-800/80 bg-zinc-900/50'
            } ${fresh ? 'ring-1 ring-cyan-500/50' : ''}`}
          >
            {pin ? (
              <div className="text-[8px] font-bold uppercase tracking-wider text-amber-400/95">Hardware pin</div>
            ) : null}
            {pin && rd.fingerprint_preview ? (
              <div className="mt-1 break-all font-mono text-[9px] font-semibold text-cyan-100/95">{rd.fingerprint_preview}</div>
            ) : null}
            <p className={`mt-1 text-[10px] leading-snug text-zinc-300 ${pin ? 'line-clamp-3' : 'line-clamp-4'}`}>
              {lead.description}
            </p>
            <div className="mt-1 flex justify-between text-[8px] text-zinc-600">
              <span className="tabular-nums">sev {(lead.severity_score * 100).toFixed(0)}</span>
              <span className="uppercase">{lead.status}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
