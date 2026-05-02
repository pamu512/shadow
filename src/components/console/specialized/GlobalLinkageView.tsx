import { RingConnectionMap } from '../../viewer/RingConnectionMap'
import { isCrossCaseWorkspacePayload, useOptionalWorkspaceData } from '../../../context/WorkspaceDataContext'

type TimelineStep = {
  case_id?: string | null
  title?: string
  month_label?: string
  position?: string
  theme?: string
  result_label?: string
}

type GraphData = {
  nodes?: Array<{ id: string; label?: string; type?: string; role?: string; glow?: boolean; device_label?: string }>
  links?: Array<{ source: string; target: string; kind?: string; color?: string | null }>
}

type PathStep = {
  role?: string
  title?: string
  subtitle?: string
}

type SharedAttr = {
  key?: string
  value?: string
  highlight?: string
}

type GlobalLinkage = {
  timeline?: TimelineStep[]
  graph_data?: GraphData
  entity_id?: string
  entity_type?: string
  relationship_path?: PathStep[]
  shared_attributes?: SharedAttr[]
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

type Hit = {
  case_id?: string
  case_name?: string
  result_label?: string
  status?: string
  created_at?: string | null
}

export function GlobalLinkageView({ payload }: { payload: Record<string, unknown> }) {
  const workspace = useOptionalWorkspaceData()
  const gl = payload.global_linkage as GlobalLinkage | undefined
  const timeline = Array.isArray(gl?.timeline) ? (gl!.timeline as TimelineStep[]) : []
  const relationshipPath = Array.isArray(gl?.relationship_path) ? (gl!.relationship_path as PathStep[]) : []
  const sharedAttrs = Array.isArray(gl?.shared_attributes) ? (gl!.shared_attributes as SharedAttr[]) : []
  const graphData = gl?.graph_data
  const requiredNarrative = typeof payload.required_narrative === 'string' ? payload.required_narrative : null
  const entityId = typeof payload.entity_id === 'string' ? payload.entity_id : '—'
  const entityType = typeof payload.entity_type === 'string' ? payload.entity_type : '—'
  const priority = typeof payload.priority === 'string' ? payload.priority : 'Normal'
  const recidivist = payload.recidivist_fraudster === true
  const hits = Array.isArray(payload.other_cases) ? (payload.other_cases as Hit[]) : []

  const nodes = graphData?.nodes?.length ? graphData.nodes : []
  const links = graphData?.links?.length ? graphData.links : []

  return (
    <div className="mt-1.5 w-full max-w-full space-y-4 rounded-lg border border-cyan-500/20 bg-gradient-to-b from-cyan-950/20 to-zinc-950/40 p-3 font-mono shadow-[0_0_28px_rgba(34,211,238,0.1)] backdrop-blur-md">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-400/95">Global intelligence match</div>
          <div className="text-xs font-semibold text-zinc-100">Infrastructure overlap — entity recidivism</div>
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
        Shared <span className="font-semibold text-zinc-200">{entityType}</span> ={' '}
        <span className="break-all text-cyan-100/90">{entityId}</span>
      </p>

      {requiredNarrative ? (
        <div className="rounded-md border border-amber-500/35 bg-amber-950/25 px-3 py-2 text-[11px] font-semibold leading-snug text-amber-100/95">
          Required narrative: <span className="font-bold text-amber-200">{requiredNarrative}</span>
        </div>
      ) : null}

      {sharedAttrs.length > 0 ? (
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
            Shared attributes (infrastructure overlap)
          </div>
          <ul className="flex flex-wrap gap-2">
            {sharedAttrs.map((a, i) => {
              const k = String(a.key ?? '—')
              const v = String(a.value ?? '—')
              const amber = a.highlight === 'amber' || k === 'IP' || k === 'Device'
              return (
                <li
                  key={`${k}-${i}`}
                  className={`rounded-md border px-2.5 py-1.5 text-[11px] ${
                    amber
                      ? 'border-amber-500/50 bg-amber-950/40 font-bold text-amber-200'
                      : 'border-zinc-700 bg-zinc-950/60 font-medium text-zinc-300'
                  }`}
                >
                  <span className="text-zinc-500">{k}:</span> {amber ? <span className="text-amber-100">{v}</span> : v}
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}

      {relationshipPath.length > 0 ? (
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Relationship path</div>
          <ol className="space-y-2 border-l border-amber-500/30 pl-3">
            {relationshipPath.map((step, i) => (
              <li key={`${step.title ?? i}-${i}`} className="text-[11px] text-zinc-300">
                <span className="font-semibold text-zinc-100">{String(step.title ?? '—')}</span>
                {step.subtitle ? <span className="mt-0.5 block text-[10px] text-zinc-500">{step.subtitle}</span> : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {timeline.length > 0 ? (
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Case timeline</div>
          <div className="flex flex-wrap items-center gap-x-1 gap-y-2 text-[11px] text-zinc-300">
            {timeline.map((step, i) => {
              const isLast = i === timeline.length - 1
              const label = String(step.title ?? 'Case')
              const when = String(step.month_label ?? '—')
              const theme = step.theme === 'bot_activity' ? 'text-amber-200/95' : 'text-zinc-200'
              return (
                <span key={`${step.case_id ?? i}-${i}`} className="flex flex-wrap items-center gap-x-1">
                  <span
                    className={`rounded-md border px-2 py-1 ${
                      step.position === 'current'
                        ? 'border-cyan-500/45 bg-cyan-950/50 text-cyan-50'
                        : 'border-zinc-700 bg-zinc-950/60'
                    }`}
                  >
                    <span className={theme}>{when}</span>
                    <span className="mx-1 text-zinc-600">·</span>
                    <span className="font-semibold text-zinc-100">{label}</span>
                  </span>
                  {!isLast ? <span className="px-0.5 text-cyan-500/80">➔</span> : null}
                </span>
              )
            })}
          </div>
        </div>
      ) : null}

      {nodes.length > 0 && links.length > 0 ? (
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Connection map</div>
          <RingConnectionMap graphData={{ nodes, links }} suppressAgentInject />
        </div>
      ) : null}

      {hits.length > 0 ? (
        <ul className="space-y-2 border-t border-zinc-800/80 pt-3">
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
                Linked case <span className="font-semibold text-zinc-100">{name}</span>
                {when !== '—' ? (
                  <>
                    {' '}
                    (<span className="text-zinc-400">{when}</span>)
                  </>
                ) : null}{' '}
                — <span className="text-fuchsia-200/90">{res}</span>
              </li>
            )
          })}
        </ul>
      ) : null}

      {workspace && isCrossCaseWorkspacePayload(payload) ? (
        <button
          type="button"
          className="w-full rounded-lg border border-cyan-500/45 bg-cyan-950/40 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-cyan-100 hover:border-cyan-400/60"
          onClick={() => workspace.setActiveWorkspaceData({ ...payload })}
        >
          Pin to workspace (Global intelligence match) ➔
        </button>
      ) : null}
    </div>
  )
}
