import { Fragment, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { ForensicModal } from '../ui/ForensicModal'

export type BotClusterRow = Record<string, unknown>

const SIGNAL_BADGE: Record<string, string> = {
  TIME_BURST: 'border-red-500/40 bg-red-950/45 text-red-200',
  SEQUENTIAL_ID_PATTERN: 'border-orange-500/35 bg-orange-950/40 text-orange-200',
  SHARED_SUBNET_UA: 'border-violet-500/40 bg-violet-950/40 text-violet-200',
  STALE_CHROME_UA: 'border-amber-500/35 bg-amber-950/40 text-amber-200',
  SHARED_SUBNET_CANVAS: 'border-cyan-500/35 bg-cyan-950/40 text-cyan-200',
  DISPOSABLE_EMAIL_DOMAIN: 'border-rose-500/35 bg-rose-950/40 text-rose-200',
  GMAIL_DOT_VARIANTS: 'border-fuchsia-500/35 bg-fuchsia-950/40 text-fuchsia-200',
  HIGH_ENTROPY_LOCAL: 'border-zinc-600 bg-zinc-900/70 text-zinc-300',
  INFRA_GEO_CONTEXT: 'border-slate-500/35 bg-slate-950/45 text-slate-200',
}

function signalClass(s: string): string {
  return SIGNAL_BADGE[s] ?? 'border-zinc-700 bg-zinc-900/60 text-zinc-400'
}

type Props = {
  clusters: BotClusterRow[]
  selectedClusterId: string | null
  onSelectCluster: (clusterId: string) => void
}

export function BotClustersWorkspaceTable({ clusters, selectedClusterId, onSelectCluster }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [idsModalClusterId, setIdsModalClusterId] = useState<string | null>(null)

  const sorted = useMemo(() => {
    return [...clusters].sort((a, b) => String(a.cluster_id ?? '').localeCompare(String(b.cluster_id ?? '')))
  }, [clusters])

  const modalCluster = useMemo(() => {
    if (!idsModalClusterId) return null
    return sorted.find((c) => String(c.cluster_id ?? '') === idsModalClusterId) ?? null
  }, [idsModalClusterId, sorted])

  const toggleExpand = (id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  return (
    <div className="w-full min-w-0 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/50">
      <div className="border-b border-zinc-800 bg-zinc-900/60 px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Clusters</div>
        <p className="mt-0.5 text-[10px] leading-snug text-zinc-600">
          Sorted by <span className="font-mono text-zinc-500">cluster_id</span>. Account id lists stay collapsed—use{' '}
          <span className="text-zinc-400">View IDs</span> for the full manifest.
        </p>
      </div>
      <div className="max-h-[min(56vh,520px)] w-full overflow-auto">
        <table className="w-full min-w-[640px] border-collapse text-left font-mono text-[10px]">
          <thead className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-900/95 backdrop-blur-sm">
            <tr>
              <th className="w-8 px-1 py-2" aria-hidden />
              <th className="px-2 py-2 text-cyan-400/90">cluster_id</th>
              <th className="px-2 py-2 text-cyan-400/90">type</th>
              <th className="px-2 py-2 text-cyan-400/90">size</th>
              <th className="min-w-[180px] px-2 py-2 text-cyan-400/90">signals</th>
              <th className="min-w-[200px] px-2 py-2 text-cyan-400/90">traits</th>
              <th className="px-2 py-2 text-cyan-400/90">accounts</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c, idx) => {
              const id = String(c.cluster_id ?? '')
              const sel = selectedClusterId === id
              const open = Boolean(expanded[id])
              const traits = (c.common_traits as string[]) || []
              const traitLine = traits.join(' · ')
              const signals = Array.isArray(c.signals) ? c.signals.filter((x): x is string => typeof x === 'string') : []
              const ids = (c.account_ids as string[]) || []
              const preview = ids.slice(0, 8)
              const rowKey = id || `row-${idx}`

              return (
                <Fragment key={rowKey}>
                  <FragmentRow
                    id={id}
                    c={c}
                    sel={sel}
                    open={open}
                    traitLine={traitLine}
                    signals={signals}
                    ids={ids}
                    preview={preview}
                    onSelect={() => onSelectCluster(id)}
                    onToggleExpand={() => toggleExpand(id)}
                    onOpenModal={() => setIdsModalClusterId(id)}
                  />
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {modalCluster ? (
        <ForensicModal
          open
          onClose={() => setIdsModalClusterId(null)}
          title={`Account IDs · ${String(modalCluster.cluster_id ?? '')}`}
          panelClassName="max-w-3xl"
        >
          <div className="max-h-[min(70vh,480px)] w-full overflow-auto font-mono text-[10px] leading-relaxed text-emerald-200/90">
            {Number(modalCluster.account_ids_truncated ?? 0) > 0 ? (
              <p className="mb-2 rounded border border-amber-500/30 bg-amber-950/25 p-2 text-amber-200/90">
                +{String(modalCluster.account_ids_truncated)} ids truncated in payload — run bot detection from workspace
                for full list if needed.
              </p>
            ) : null}
            <ul className="space-y-0.5">
              {((modalCluster.account_ids as string[]) || []).map((aid) => (
                <li key={aid}>{aid}</li>
              ))}
            </ul>
          </div>
        </ForensicModal>
      ) : null}
    </div>
  )
}

function FragmentRow({
  id,
  c,
  sel,
  open,
  traitLine,
  signals,
  ids,
  preview,
  onSelect,
  onToggleExpand,
  onOpenModal,
}: {
  id: string
  c: BotClusterRow
  sel: boolean
  open: boolean
  traitLine: string
  signals: string[]
  ids: string[]
  preview: string[]
  onSelect: () => void
  onToggleExpand: () => void
  onOpenModal: () => void
}) {
  return (
    <>
      <tr
        className={`cursor-pointer border-b border-zinc-800/80 transition-colors hover:bg-zinc-900/40 ${
          sel ? 'bg-cyan-950/35 ring-1 ring-inset ring-cyan-500/30' : ''
        }`}
        onClick={onSelect}
      >
        <td className="px-1 py-1 align-middle">
          <button
            type="button"
            className="flex h-7 w-7 items-center justify-center rounded border border-transparent text-zinc-500 hover:border-zinc-700 hover:bg-zinc-900 hover:text-zinc-300"
            aria-expanded={open}
            aria-label={open ? 'Collapse row' : 'Expand row'}
            onClick={(e) => {
              e.stopPropagation()
              onToggleExpand()
            }}
          >
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        </td>
        <td className="max-w-[160px] truncate px-2 py-1.5 font-medium text-zinc-100" title={id}>
          {id}
        </td>
        <td className="max-w-[120px] truncate px-2 py-1.5 text-zinc-400" title={String(c.cluster_type ?? '')}>
          {String(c.cluster_type ?? '').replace(/_/g, ' ')}
        </td>
        <td className="whitespace-nowrap px-2 py-1.5 tabular-nums text-amber-200/90">{String(c.size ?? '')}</td>
        <td className="px-2 py-1.5">
          <div className="flex flex-wrap gap-1">
            {signals.map((s) => (
              <span
                key={s}
                className={`inline-block rounded border px-1 py-px text-[8px] font-semibold uppercase tracking-wide ${signalClass(s)}`}
              >
                {s.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        </td>
        <td className="max-w-[280px] px-2 py-1.5 text-zinc-500" title={traitLine}>
          <span className="line-clamp-2">{traitLine || '—'}</span>
        </td>
        <td className="whitespace-nowrap px-2 py-1.5">
          <button
            type="button"
            className="rounded border border-zinc-700 bg-zinc-900/80 px-2 py-1 text-[9px] font-semibold uppercase tracking-wide text-zinc-300 hover:border-cyan-500/45 hover:text-cyan-200"
            onClick={(e) => {
              e.stopPropagation()
              onOpenModal()
            }}
          >
            View IDs
          </button>
          <span className="ml-2 text-zinc-600">({ids.length})</span>
        </td>
      </tr>
      {open ? (
        <tr className="border-b border-zinc-800/80 bg-zinc-950/80">
          <td colSpan={7} className="px-4 py-2">
            <div className="text-[9px] font-semibold uppercase tracking-wider text-zinc-600">Preview (first 8)</div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-emerald-200/85">
              {preview.length ? preview.map((x) => <span key={x}>{x}</span>) : <span className="text-zinc-600">—</span>}
            </div>
            {ids.length > 8 ? (
              <button
                type="button"
                className="mt-2 text-[9px] font-semibold uppercase tracking-wide text-cyan-400/90 hover:text-cyan-300"
                onClick={(e) => {
                  e.stopPropagation()
                  onOpenModal()
                }}
              >
                Open full list in modal →
              </button>
            ) : null}
          </td>
        </tr>
      ) : null}
    </>
  )
}

