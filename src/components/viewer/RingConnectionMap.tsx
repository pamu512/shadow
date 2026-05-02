import ForceGraph2D from 'react-force-graph-2d'
import { useCallback, useMemo, useRef } from 'react'
import { AGENT_INJECT_EVENT } from '../../lib/api'

export type RingGraphNode = {
  id: string
  type?: string
  label?: string
  role?: string
  glow?: boolean
  community_id?: number | null
  degree?: number
  device_label?: string
}

export type RingGraphLink = {
  source: string
  target: string
  kind?: string
  lineDash?: boolean
  color?: string | null
}

type Props = {
  graphData: { nodes: RingGraphNode[]; links: RingGraphLink[] }
  onNodeFocus?: (node: RingGraphNode) => void
  /** When true, node clicks do not dispatch AGENT_INJECT (e.g. global warehouse linkage maps). */
  suppressAgentInject?: boolean
}

export function RingConnectionMap({ graphData, onNodeFocus, suppressAgentInject }: Props) {
  const fgRef = useRef<{ zoomToFit?: (ms: number, pad: number) => void } | null>(null)

  const data = useMemo(() => {
    const nodes = (graphData.nodes || []).map((n) => ({ ...n }))
    const links = (graphData.links || []).map((l) => ({
      ...l,
      source: typeof l.source === 'object' && l.source && 'id' in l.source ? (l.source as { id: string }).id : l.source,
      target: typeof l.target === 'object' && l.target && 'id' in l.target ? (l.target as { id: string }).id : l.target,
    }))
    return { nodes, links }
  }, [graphData])

  const onNodeClick = useCallback(
    (node: object) => {
      const n = node as RingGraphNode
      onNodeFocus?.(n)
      if (suppressAgentInject) {
        return
      }
      const meta = {
        id: n.id,
        type: n.type ?? 'account',
        role: n.role,
        community_id: n.community_id,
        degree: n.degree,
        label: n.label ?? n.id,
        device_label: n.device_label,
      }
      const text =
        `/investigate — Fraud Ring graph node selected.\n` +
        `Metadata (JSON): ${JSON.stringify(meta, null, 2)}\n` +
        `Summarize how this node fits the ring: infrastructure ties, payment cycles, and counterparty risk.`
      window.dispatchEvent(
        new CustomEvent(AGENT_INJECT_EVENT, {
          detail: { text, persona_id: 'fraud_ring_detective' },
        }),
      )
    },
    [onNodeFocus, suppressAgentInject],
  )

  if (!data.nodes.length) {
    return (
      <div className="flex min-h-[200px] items-center justify-center rounded-lg border border-dashed border-zinc-800 font-mono text-[11px] text-zinc-600">
        No graph nodes — run ring detection first.
      </div>
    )
  }

  return (
    <div className="relative h-[min(62vh,520px)] min-h-[280px] w-full overflow-hidden rounded-xl border border-zinc-800 bg-[#070708]">
      <ForceGraph2D
        ref={fgRef as never}
        graphData={data}
        backgroundColor="#070708"
        nodeLabel={(n: object) => String((n as RingGraphNode).id)}
        linkDirectionalArrowLength={3.5}
        linkDirectionalArrowRelPos={1}
        linkColor={(l: object) =>
          String((l as RingGraphLink).color || 'rgba(148,163,184,0.42)')
        }
        linkWidth={(l: object) => ((l as RingGraphLink).kind === 'payment' ? 1.2 : 0.8)}
        linkLineDash={(l: object) => ((l as RingGraphLink).lineDash ? [5, 4] : null)}
        onNodeClick={onNodeClick}
        d3VelocityDecay={0.25}
        cooldownTicks={120}
        onEngineStop={() => {
          try {
            fgRef.current?.zoomToFit?.(400, 24)
          } catch {
            /* ignore */
          }
        }}
        nodeCanvasObject={(n, ctx, globalScale) => {
          const node = n as RingGraphNode & { x?: number; y?: number }
          const x = node.x ?? 0
          const y = node.y ?? 0
          const sz = node.type === 'device' || node.type === 'employee' ? 5 : 6
          ctx.save()
          if (node.glow) {
            ctx.shadowColor = 'rgba(239,68,68,0.85)'
            ctx.shadowBlur = 16 / Math.max(0.35, globalScale)
          }
          const fill =
            node.type === 'device'
              ? 'rgba(167,139,250,0.95)'
              : node.type === 'employee'
                ? 'rgba(251,146,60,0.95)'
                : node.role === 'hub'
                  ? 'rgba(248,113,113,0.95)'
                  : node.role === 'bridge'
                    ? 'rgba(250,204,21,0.92)'
                    : node.role === 'mule'
                      ? 'rgba(56,189,248,0.92)'
                      : 'rgba(148,163,184,0.9)'
          ctx.beginPath()
          if (node.type === 'device' || node.type === 'employee') {
            ctx.rect(x - sz, y - sz, sz * 2, sz * 2)
          } else {
            ctx.arc(x, y, sz, 0, 2 * Math.PI)
          }
          ctx.fillStyle = fill
          ctx.fill()
          ctx.restore()
          if (globalScale > 0.55) {
            const lbl = (node.label || node.id).slice(0, 14)
            ctx.font = `${10 / globalScale}px JetBrains Mono, monospace`
            ctx.textAlign = 'center'
            ctx.textBaseline = 'top'
            ctx.fillStyle = 'rgba(228,228,231,0.82)'
            ctx.fillText(lbl, x, y + sz + 2 / globalScale)
          }
        }}
        nodePointerAreaPaint={(n, color, ctx) => {
          const node = n as RingGraphNode & { x?: number; y?: number }
          const x = node.x ?? 0
          const y = node.y ?? 0
          const sz = 10
          ctx.fillStyle = color
          ctx.fillRect(x - sz, y - sz, sz * 2, sz * 2)
        }}
      />
      <div className="pointer-events-none absolute left-2 top-2 max-w-[220px] rounded border border-zinc-800/90 bg-zinc-950/85 px-2 py-1.5 font-mono text-[9px] leading-relaxed text-zinc-500">
        <div className="font-semibold text-zinc-400">Legend</div>
        <div>
          <span className="text-slate-400">● account</span> · <span className="text-violet-300">■ device</span> ·{' '}
          <span className="text-orange-300">■ internal</span>
        </div>
        <div>
          solid ≈ payment · dashed ≈ shared data
          <span className="text-red-300/90"> · glow = high-risk cluster / hub</span>
        </div>
      </div>
    </div>
  )
}
