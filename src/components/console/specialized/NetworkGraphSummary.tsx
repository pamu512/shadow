export function NetworkGraphSummary({ payload }: { payload: Record<string, unknown> }) {
  const gd = payload.graph_data as { nodes?: unknown[]; links?: unknown[] } | undefined
  const gn = payload.graph_nodes
  const summary = (payload.graph_summary as Record<string, unknown>) || {}
  const nodes = Array.isArray(gn)
    ? gn.length
    : Array.isArray(gd?.nodes)
      ? gd!.nodes!.length
      : typeof summary.nodes === 'number'
        ? summary.nodes
        : '—'
  const edges = typeof summary.edges === 'number' ? summary.edges : Array.isArray(gd?.links) ? gd!.links!.length : '—'
  const acct = typeof summary.account_nodes === 'number' ? summary.account_nodes : '—'
  const cycles = typeof payload.cycles_found === 'number' ? payload.cycles_found : null
  const communities = typeof payload.community_count === 'number' ? payload.community_count : null
  const mh = payload.multi_hop_scan as Record<string, unknown> | undefined

  return (
    <div className="mt-1.5 w-full max-w-full space-y-2 rounded-lg border border-zinc-800 bg-zinc-900/80 p-3 font-mono shadow-[0_0_28px_rgba(139,92,246,0.12)] backdrop-blur-md">
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-400/90">Network graph</div>
      <div className="text-xs font-semibold text-zinc-100">Fraud ring visualization payload</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { k: 'Vis nodes', v: nodes },
          { k: 'Vis links', v: edges },
          { k: 'Accounts', v: acct },
          { k: 'Cycles', v: cycles ?? '—' },
        ].map((x) => (
          <div key={x.k} className="rounded border border-zinc-800/80 bg-[#08080a]/90 px-2 py-2 text-center">
            <div className="text-[9px] font-medium uppercase tracking-wider text-zinc-600">{x.k}</div>
            <div className="mt-1 text-sm font-bold tabular-nums text-violet-200/95">{String(x.v)}</div>
          </div>
        ))}
      </div>
      {communities != null ? (
        <div className="text-[10px] text-zinc-500">
          Communities <span className="text-zinc-300">{communities}</span>
        </div>
      ) : null}
      {mh && typeof mh === 'object' ? (
        <div className="rounded border border-cyan-500/20 bg-cyan-950/15 px-2 py-2 text-[10px] leading-relaxed text-cyan-100/85">
          <span className="font-semibold uppercase tracking-wider text-cyan-400/90">Multi-hop scan · </span>
          {typeof mh.shared_device_multi_account_bridges === 'number' ? (
            <span className="text-zinc-300">
              Shared-device bridges (≥2 accounts/device):{' '}
              <span className="font-bold text-cyan-200">{mh.shared_device_multi_account_bridges}</span>
            </span>
          ) : null}
          {mh.three_hop_narrative_ready === true ? (
            <span className="mt-1 block text-[9px] text-zinc-500">
              Graph supports ≥3-hop Account → shared attribute → Account → device narratives — cite linkage_alerts
              and cycles before naming kingpins.
            </span>
          ) : (
            <span className="mt-1 block text-[9px] text-zinc-500">
              Sparse graph — confirm columns (device, payer, payee) before strong multi-hop claims.
            </span>
          )}
        </div>
      ) : null}
      {typeof payload.visualization_note === 'string' && payload.visualization_note ? (
        <p className="rounded border border-amber-500/25 bg-amber-950/20 px-2 py-1.5 text-[10px] text-amber-200/90">
          {payload.visualization_note}
        </p>
      ) : null}
      <p className="text-[9px] leading-snug text-zinc-600">
        Open the workspace <span className="text-zinc-400">Connection Map</span> tab to explore the interactive graph.
      </p>
    </div>
  )
}
