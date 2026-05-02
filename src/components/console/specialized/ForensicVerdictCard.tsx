type TrustVelocity = {
  completed_tx_count?: number
  avg_completed_amount?: number
  focal_amount?: number
  amount_ratio_vs_avg?: number
}

type IpDev = {
  prior_completed_shares_ip?: boolean
  prior_completed_shares_device?: boolean
  interpretation?: string
}

export function ForensicVerdictCard({ payload }: { payload: Record<string, unknown> }) {
  const agentType = typeof payload.agent_type === 'string' ? payload.agent_type : 'general'
  const risk = typeof payload.risk_score === 'number' ? payload.risk_score : null
  const verdict = typeof payload.verdict_label === 'string' ? payload.verdict_label : '—'
  const seasoning =
    typeof payload.seasoning_assessment === 'string' ? payload.seasoning_assessment : null
  const tv = (payload.trust_vs_velocity as TrustVelocity) || {}
  const ipd = (payload.ip_device_consistency as IpDev) || {}
  const bullets = Array.isArray(payload.reasoning_bullets) ? (payload.reasoning_bullets as string[]) : []

  const pct = risk != null ? Math.min(100, Math.max(0, risk)) : 0
  const barClass =
    pct >= 75 ? 'from-rose-600/95 to-amber-500/85' : pct >= 45 ? 'from-amber-600/90 to-yellow-500/80' : 'from-emerald-700/90 to-emerald-500/75'

  return (
    <div className="mt-1.5 w-full max-w-full space-y-3 rounded-lg border border-fuchsia-500/25 bg-gradient-to-b from-fuchsia-950/20 to-zinc-950/80 p-3 font-mono shadow-[0_0_28px_rgba(192,38,211,0.12)] backdrop-blur-md">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-zinc-800/80 pb-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fuchsia-400/95">Forensic verdict</div>
          <div className="text-xs font-semibold text-zinc-100">
            {agentType === 'chargeback' ? 'Chargeback specialist' : 'General analyst · transaction forensics'}
          </div>
        </div>
        {risk != null ? (
          <div className="text-right">
            <div className="text-[9px] font-medium uppercase tracking-wider text-zinc-500">Risk score</div>
            <div className="text-2xl font-bold tabular-nums text-fuchsia-200">{risk}</div>
            <div className="text-[9px] text-zinc-600">/ 100</div>
          </div>
        ) : null}
      </div>

      {risk != null ? (
        <div>
          <div className="mb-1 h-2.5 w-full overflow-hidden rounded-full bg-zinc-800">
            <div className={`h-full rounded-full bg-gradient-to-r ${barClass}`} style={{ width: `${pct}%` }} />
          </div>
        </div>
      ) : null}

      <div className="rounded-md border border-zinc-800/80 bg-[#08080a]/90 p-2.5">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">Reasoning</div>
        <p className="mt-1 text-[11px] font-medium leading-relaxed text-zinc-200">{verdict}</p>
        {seasoning ? (
          <p className="mt-2 rounded border border-rose-500/35 bg-rose-950/40 px-2 py-1.5 text-[10px] font-semibold text-rose-100">
            {seasoning}
          </p>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          { k: 'Warm-up orders', v: tv.completed_tx_count },
          { k: 'Avg completed $', v: tv.avg_completed_amount != null ? `$${Number(tv.avg_completed_amount).toFixed(2)}` : '—' },
          { k: 'Focal $', v: tv.focal_amount != null ? `$${Number(tv.focal_amount).toFixed(2)}` : '—' },
          { k: '× vs avg', v: tv.amount_ratio_vs_avg != null ? `${Number(tv.amount_ratio_vs_avg).toFixed(1)}×` : '—' },
        ].map((x) => (
          <div key={x.k} className="rounded border border-zinc-800/80 bg-zinc-950/50 px-2 py-2 text-center">
            <div className="text-[8px] font-medium uppercase tracking-wider text-zinc-600">{x.k}</div>
            <div className="mt-1 text-sm font-bold tabular-nums text-zinc-100">{x.v ?? '—'}</div>
          </div>
        ))}
      </div>

      <div className="rounded-md border border-zinc-800/70 bg-zinc-950/40 px-2.5 py-2 text-[10px] text-zinc-400">
        <span className="font-semibold text-zinc-500">IP / device vs warm-up: </span>
        {ipd.prior_completed_shares_ip ? <span className="text-emerald-300/90">IP reuse · </span> : null}
        {ipd.prior_completed_shares_device ? <span className="text-emerald-300/90">Device reuse · </span> : null}
        <span className="text-zinc-500">{String(ipd.interpretation ?? '—')}</span>
      </div>

      {bullets.length > 0 ? (
        <ul className="list-inside list-disc space-y-1 text-[10px] leading-relaxed text-zinc-400">
          {bullets.map((b, i) => (
            <li key={i} className="marker:text-fuchsia-500/80">
              {b.replace(/\*\*/g, '')}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
