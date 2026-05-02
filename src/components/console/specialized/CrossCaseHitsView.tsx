import { isCrossCaseWorkspacePayload, useOptionalWorkspaceData } from '../../../context/WorkspaceDataContext'

function formatCaseWhen(iso: string | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
    return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
  } catch {
    return iso
  }
}

type Hit = {
  case_id?: string
  case_name?: string
  result_label?: string
  status?: string
  created_at?: string | null
}

export function CrossCaseHitsView({ payload }: { payload: Record<string, unknown> }) {
  const workspace = useOptionalWorkspaceData()
  const entityId = typeof payload.entity_id === 'string' ? payload.entity_id : '—'
  const entityType = typeof payload.entity_type === 'string' ? payload.entity_type : '—'
  const priority = typeof payload.priority === 'string' ? payload.priority : 'Normal'
  const recidivist = payload.recidivist_fraudster === true
  const hits = Array.isArray(payload.other_cases) ? (payload.other_cases as Hit[]) : []

  return (
    <div className="mt-1.5 w-full max-w-full space-y-3 rounded-lg border border-amber-500/25 bg-amber-950/15 p-3 font-mono shadow-[0_0_24px_rgba(245,158,11,0.12)] backdrop-blur-md">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-400/95">Global warehouse</div>
          <div className="text-xs font-semibold text-zinc-100">Cross-case matches</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {recidivist ? (
            <span className="rounded-full border border-red-500/50 bg-red-950/50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-red-200">
              Recidivist fraudster
            </span>
          ) : null}
          <span className="rounded-full border border-zinc-700 bg-zinc-900/80 px-2.5 py-1 text-[10px] font-semibold text-zinc-300">
            {priority}
          </span>
        </div>
      </div>
      <p className="text-[10px] leading-relaxed text-zinc-500">
        Entity <span className="font-semibold text-zinc-200">{entityType}</span> ={' '}
        <span className="break-all text-amber-100/90">{entityId}</span>
      </p>
      {hits.length === 0 ? (
        <p className="text-[11px] text-zinc-500">No other cases indexed for this entity yet.</p>
      ) : (
        <ul className="space-y-2">
          {hits.map((h, i) => {
            const cid = String(h.case_id ?? '')
            const name = String(h.case_name ?? cid)
            const when = formatCaseWhen(h.created_at ?? undefined)
            const res = String(h.result_label ?? h.status ?? 'Unknown')
            return (
              <li
                key={`${cid}-${i}`}
                className="rounded-md border border-zinc-800/90 bg-zinc-950/50 px-3 py-2 text-[11px] leading-snug text-zinc-300"
              >
                Also appeared in <span className="font-semibold text-zinc-100">{name}</span>
                {when !== '—' ? (
                  <>
                    {' '}
                    (<span className="text-zinc-400">{when}</span>)
                  </>
                ) : null}{' '}
                — Result: <span className="text-fuchsia-200/90">{res}</span>
                {cid ? (
                  <span className="mt-1 block font-mono text-[9px] text-zinc-600">case_id · {cid}</span>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
      {workspace && isCrossCaseWorkspacePayload(payload) ? (
        <button
          type="button"
          className="w-full rounded-lg border border-cyan-500/45 bg-cyan-950/40 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-cyan-100 hover:border-cyan-400/60"
          onClick={() => workspace.setActiveWorkspaceData({ ...payload })}
        >
          Pin to workspace (Cross-case matches) ➔
        </button>
      ) : null}
    </div>
  )
}
