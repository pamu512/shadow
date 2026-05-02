/** Hardware hash + associated IPs — driven by `detect_bot_clusters` → `hardware_ip_forensics`. */
export function BotHardwareForensicCard({ payload }: { payload: Record<string, unknown> }) {
  const hw = (payload.hardware_ip_forensics as Record<string, unknown> | undefined) ?? {}
  const critical = hw.critical_hardware_spoofing === true
  const verdict = typeof hw.verdict_label === 'string' ? hw.verdict_label : '—'
  const fp =
    typeof hw.dominant_canvas_fingerprint === 'string'
      ? hw.dominant_canvas_fingerprint
      : typeof hw.dominant_canvas_fingerprint_full === 'string'
        ? String(hw.dominant_canvas_fingerprint_full).slice(0, 96)
        : '—'
  const acct = typeof hw.unique_accounts_on_dominant === 'number' ? hw.unique_accounts_on_dominant : null
  const dips = typeof hw.unique_ips_on_dominant === 'number' ? hw.unique_ips_on_dominant : null
  const share = typeof hw.share_pct_on_dominant === 'number' ? hw.share_pct_on_dominant : null
  const infra =
    typeof hw.infrastructure_summary === 'string' ? hw.infrastructure_summary : null
  const rec = typeof hw.recommended_action === 'string' ? hw.recommended_action : null
  const ips = Array.isArray(hw.associated_ips) ? (hw.associated_ips as string[]).filter((x) => typeof x === 'string') : []
  const degraded = payload.analysis_degraded === true
  const clusters = Array.isArray(payload.clusters) ? payload.clusters.length : 0

  return (
    <div className="mt-1.5 w-full max-w-full space-y-3 rounded-lg border border-rose-500/25 bg-gradient-to-b from-rose-950/15 to-zinc-950/90 p-3 font-mono shadow-[0_0_28px_rgba(244,63,94,0.1)] backdrop-blur-md">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-zinc-800/80 pb-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-rose-400/95">Bot detection</div>
          <div className="text-xs font-semibold text-zinc-100">Hardware vs IP</div>
        </div>
        {degraded ? (
          <span className="rounded border border-amber-500/40 bg-amber-950/40 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-amber-200">
            Partial schema
          </span>
        ) : null}
      </div>

      {critical ? (
        <div className="rounded-md border-2 border-rose-600/70 bg-rose-950/50 px-3 py-2 text-center text-[11px] font-extrabold uppercase tracking-[0.12em] text-rose-100 shadow-[0_0_20px_rgba(225,29,72,0.35)]">
          CRITICAL: HARDWARE SPOOFING DETECTED
        </div>
      ) : null}

      <div className="rounded-lg border border-zinc-700/80 bg-zinc-950/70 px-3 py-3">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">Hardware hash</div>
        <div className="mt-1.5 break-all text-sm font-bold leading-snug text-cyan-100">{fp}</div>
      </div>

      <div className="rounded-md border border-zinc-800/80 bg-[#08080a]/90 px-2.5 py-2">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-zinc-500">Verdict</div>
        <p className="mt-1 text-[11px] font-semibold leading-snug text-zinc-100">{verdict}</p>
        {infra ? <p className="mt-1.5 text-[10px] leading-relaxed text-zinc-400">{infra}</p> : null}
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          { k: 'Accounts (dominant)', v: acct != null ? String(acct) : '—' },
          { k: 'Unique IPs', v: dips != null ? String(dips) : '—' },
          { k: 'Row share %', v: share != null ? `${share.toFixed(1)}%` : '—' },
        ].map((x) => (
          <div key={x.k} className="rounded border border-zinc-800/80 bg-zinc-950/50 px-2 py-2 text-center">
            <div className="text-[8px] font-medium uppercase tracking-wider text-zinc-600">{x.k}</div>
            <div className="mt-1 text-sm font-bold tabular-nums text-zinc-100">{x.v}</div>
          </div>
        ))}
      </div>

      <div>
        <div className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-zinc-500">Associated IPs</div>
        <div className="max-h-40 overflow-y-auto rounded-md border border-zinc-800/80 bg-zinc-950/40 px-2 py-2 text-[10px] leading-relaxed text-zinc-300 [scrollbar-width:thin]">
          {ips.length === 0 ? (
            <span className="text-zinc-600">No IP list (missing ip column or empty filter).</span>
          ) : (
            <ul className="space-y-0.5">
              {ips.slice(0, 80).map((ip) => (
                <li key={ip} className="font-mono text-cyan-200/90">
                  {ip}
                </li>
              ))}
              {ips.length > 80 ? (
                <li className="pt-1 text-zinc-600">+{ips.length - 80} more (see raw JSON)</li>
              ) : null}
            </ul>
          )}
        </div>
      </div>

      {rec ? (
        <div className="rounded-md border border-emerald-500/25 bg-emerald-950/20 px-2.5 py-2 text-[10px] leading-relaxed text-emerald-100/90">
          <span className="font-bold text-emerald-400/95">Recommended action · </span>
          {rec}
        </div>
      ) : null}

      {clusters > 0 ? (
        <p className="text-center text-[9px] font-medium uppercase tracking-wider text-zinc-600">
          {clusters} cluster{clusters === 1 ? '' : 's'} in payload — expand raw output for full cluster objects.
        </p>
      ) : null}
    </div>
  )
}
