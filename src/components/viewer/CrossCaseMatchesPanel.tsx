import { activateCase } from '../../lib/api'
import type { CaseOut } from '../../lib/types'
import { isCrossCaseWorkspacePayload } from '../../context/WorkspaceDataContext'

type Hit = {
  case_id?: string
  case_name?: string
  result_label?: string
  status?: string
  created_at?: string | null
}

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

type Props = {
  payload: Record<string, unknown> | null
  activeCaseId: string | null
  onActivateCase: (c: CaseOut) => void
}

/** Warehouse overlap hits — render only when `payload` is a valid cross-case tool result (saves vertical space). */
export function CrossCaseMatchesPanel({ payload, activeCaseId, onActivateCase }: Props) {
  if (!payload || !isCrossCaseWorkspacePayload(payload)) {
    return null
  }

  const entityId = typeof payload.entity_id === 'string' ? payload.entity_id : '—'
  const entityType = typeof payload.entity_type === 'string' ? payload.entity_type : '—'
  const recidivist = payload.recidivist_fraudster === true
  const priority = typeof payload.priority === 'string' ? payload.priority : 'Normal'
  const hits = Array.isArray(payload.other_cases) ? (payload.other_cases as Hit[]) : []

  return (
    <div className="min-h-0 flex-1 overflow-auto border-t border-zinc-800/80 bg-[#08080a]/40 p-3 [scrollbar-width:thin]">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-400/95">Cross-case matches</div>
          <div className="text-[11px] text-zinc-400">
            {entityType} · <span className="break-all text-zinc-200">{entityId}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {recidivist ? (
            <span className="rounded border border-red-500/45 bg-red-950/40 px-2 py-0.5 text-[9px] font-bold uppercase text-red-200">
              Recidivist
            </span>
          ) : null}
          <span className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-0.5 text-[9px] text-zinc-400">{priority}</span>
        </div>
      </div>
      {hits.length === 0 ? (
        <p className="text-[10px] text-zinc-600">No other cases for this entity (excluding current case).</p>
      ) : (
        <ul className="max-h-[min(50vh,360px)] space-y-2 overflow-auto pr-1 [scrollbar-width:thin]">
          {hits.map((h, i) => {
            const cid = String(h.case_id ?? '')
            const name = String(h.case_name ?? 'Case')
            const when = formatCaseWhen(h.created_at ?? undefined)
            const res = String(h.result_label ?? h.status ?? 'Unknown')
            const isCurrent = activeCaseId && cid === activeCaseId
            return (
              <li
                key={`${cid}-${i}`}
                className="rounded-md border border-zinc-800/80 bg-zinc-950/60 px-2.5 py-2 text-[10px] leading-snug text-zinc-300"
              >
                <div>
                  Entity also appeared in <span className="font-semibold text-zinc-100">{name}</span>
                  {when !== '—' ? (
                    <>
                      {' '}
                      (<span className="text-zinc-500">{when}</span>)
                    </>
                  ) : null}{' '}
                  — Result: <span className="text-fuchsia-200/90">{res}</span>
                </div>
                {cid && !isCurrent ? (
                  <button
                    type="button"
                    className="mt-1.5 text-[9px] font-semibold uppercase tracking-wide text-cyan-400 hover:text-cyan-300"
                    onClick={() => {
                      void (async () => {
                        try {
                          const c = await activateCase(cid)
                          onActivateCase(c)
                        } catch {
                          /* ignore */
                        }
                      })()
                    }}
                  >
                    Open case →
                  </button>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
