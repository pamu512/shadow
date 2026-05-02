type Props = {
  botClusters: Record<string, unknown> | null
}

export function HardwareFingerprintGallery({ botClusters }: Props) {
  const hw = botClusters?.hardware_ip_forensics as Record<string, unknown> | undefined
  const ok = botClusters?.ok === true

  if (!botClusters) {
    return (
      <div className="p-4 text-[12px] leading-relaxed text-zinc-500">
        Run <span className="font-mono text-zinc-400">detect_bot_clusters_tool</span> from the investigation agent. When
        results land, use <span className="text-zinc-300">Send to Workspace</span> on the tool card to load hardware
        forensics here.
      </div>
    )
  }

  if (!ok || !hw || typeof hw !== 'object') {
    return (
      <div className="p-4 text-[12px] text-zinc-500">
        No hardware fingerprint block in the last cluster result. Re-run detection after confirming column mapping.
      </div>
    )
  }

  const fp = String(hw.dominant_canvas_fingerprint ?? hw.dominant_canvas_fingerprint_full ?? '').trim()
  const share = hw.share_pct_on_dominant
  const acct = hw.unique_accounts_on_dominant
  const ips = hw.unique_ips_on_dominant
  const verdict = String(hw.verdict_label ?? '—')

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
      <div className="rounded-lg border border-cyan-500/35 bg-cyan-950/15 p-3">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-cyan-400/90">Dominant fingerprint</div>
        <p className="mt-2 break-all font-mono text-[11px] leading-relaxed text-cyan-100/95">{fp || '—'}</p>
        <div className="mt-3 flex flex-wrap gap-3 font-mono text-[11px] text-zinc-400">
          {typeof share === 'number' ? (
            <span>
              <span className="text-zinc-600">Share</span> {Number(share).toFixed(1)}%
            </span>
          ) : null}
          {typeof acct === 'number' ? (
            <span>
              <span className="text-zinc-600">Accounts</span> {acct}
            </span>
          ) : null}
          {typeof ips === 'number' ? (
            <span>
              <span className="text-zinc-600">IPs</span> {ips}
            </span>
          ) : null}
        </div>
        <div className="mt-2 text-[11px] font-medium text-zinc-300">Verdict · {verdict}</div>
      </div>
      <p className="text-[11px] leading-relaxed text-zinc-500">
        Cross-reference dominant canvas strings in the Global Warehouse from entity chips in the transcript, or emit a
        hardware lead from the tool card.
      </p>
    </div>
  )
}
