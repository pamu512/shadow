import { isBotClusterWorkspacePayload, useOptionalWorkspaceData } from '../../../context/WorkspaceDataContext'

const SIGNAL_SIMILARITY: Record<string, string> = {
  SHARED_SUBNET_UA: '~98% shared User-Agent + /24 subnet overlap',
  SHARED_SUBNET_CANVAS: '~95% identical canvas fingerprint within subnet',
  TIME_BURST: 'High temporal density — coordinated signup burst',
  SEQUENTIAL_ID_PATTERN: 'Sequential synthetic handles (series pattern)',
  STALE_CHROME_UA: 'Stale / mismatched Chrome build vs claimed OS',
  DISPOSABLE_EMAIL_DOMAIN: 'Disposable email domain concentration',
  GMAIL_DOT_VARIANTS: 'Gmail dot-trick variants on shared infrastructure',
  HIGH_ENTROPY_LOCAL: 'High-entropy locals — programmatic strings',
  INFRA_GEO_CONTEXT: 'Hosting / datacenter geo context overlap',
  HUMANOID_BOT_RING: 'High-confidence Humanoid pattern — shared canvas / browser hash with IP rotation',
  CANVAS_HARDWARE_COLLISION: 'Many distinct IPs and identities behind one hardware fingerprint',
}

export function BotClusterView({
  payload,
  variant = 'default',
}: {
  payload: Record<string, unknown>
  variant?: 'default' | 'cluster_strength'
}) {
  const workspace = useOptionalWorkspaceData()
  const clusters = Array.isArray(payload.clusters) ? payload.clusters : []
  const hardwareCards = Array.isArray(payload.hardware_overlap_cards)
    ? (payload.hardware_overlap_cards as Record<string, unknown>[])
    : []
  const semMap = payload.semantic_column_mapping
  const sga = payload.schema_grounded_analysis
  const canvasDist = Array.isArray(payload.canvas_fingerprint_distribution)
    ? (payload.canvas_fingerprint_distribution as Record<string, unknown>[])
    : []
  const spoof = payload.hardware_spoofing_assessment as Record<string, unknown> | null | undefined
  const density = typeof payload.bot_density_pct === 'number' ? payload.bot_density_pct : 0
  const rowCount = typeof payload.row_count === 'number' ? payload.row_count : null
  const totalFlagged = clusters.reduce((acc, c) => {
    if (typeof c === 'object' && c !== null && 'size' in c) return acc + Number((c as { size?: number }).size ?? 0)
    return acc
  }, 0)

  const pct = Math.min(100, Math.max(0, density))
  const manualPct = Math.min(100, Math.max(0, 100 - pct))
  const topCluster = clusters[0] as Record<string, unknown> | undefined
  const topSignals = Array.isArray(topCluster?.signals)
    ? (topCluster!.signals as string[]).filter((x): x is string => typeof x === 'string')
    : []
  const similarityLines = topSignals.map((sig) => SIGNAL_SIMILARITY[sig] ?? `${sig.replace(/_/g, ' ')} correlation`)

  const canvasCluster = clusters.some((c) => {
    if (typeof c !== 'object' || c === null) return false
    const sigs = (c as { signals?: unknown }).signals
    if (!Array.isArray(sigs)) return false
    return sigs.includes('HUMANOID_BOT_RING') || sigs.includes('CANVAS_HARDWARE_COLLISION')
  })
  const primarySignal =
    typeof payload.primary_signal === 'string'
      ? payload.primary_signal
      : hardwareCards.length > 0 ||
          canvasCluster ||
          canvasDist.length > 0 ||
          (spoof != null && typeof spoof.label === 'string')
        ? 'canvas_hardware'
        : null
  const primaryRationale =
    typeof payload.primary_signal_rationale === 'string' ? payload.primary_signal_rationale : null
  const insightsReady =
    payload.cluster_insights_ready === true ||
    (payload.ok !== false &&
      (typeof payload.bot_density_pct === 'number' ||
        hardwareCards.length > 0 ||
        clusters.length > 0 ||
        canvasDist.length > 0))

  const topCanvas = canvasDist[0]
  const topCanvasRowCount = topCanvas && typeof topCanvas.row_count === 'number' ? topCanvas.row_count : 0
  const topCanvasDip =
    topCanvas && typeof topCanvas.distinct_ip_count === 'number' ? topCanvas.distinct_ip_count : 0
  const topCanvasShare = topCanvas && typeof topCanvas.share_pct === 'number' ? topCanvas.share_pct : 0
  const topCanvasFp =
    topCanvas && typeof topCanvas.fingerprint_preview === 'string' ? topCanvas.fingerprint_preview : '—'
  const ipVisualDots = Math.min(36, Math.max(6, topCanvasDip))

  return (
    <div className="mt-1.5 w-full max-w-full space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/80 p-3 font-mono shadow-[0_0_28px_rgba(244,63,94,0.08)] backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">Bot hunter</div>
          <div className="text-xs font-semibold text-zinc-100">
            {insightsReady ? 'Cluster insights' : variant === 'cluster_strength' ? 'Cluster strength · operator view' : 'Cluster summary'}
          </div>
        </div>
        <span className="rounded-full border border-rose-500/40 bg-rose-950/50 px-3 py-1 text-[10px] font-bold tabular-nums text-rose-100 shadow-[0_0_16px_rgba(244,63,94,0.2)]">
          {variant === 'cluster_strength'
            ? `${clusters.length} cluster${clusters.length === 1 ? '' : 's'} · strength index ${pct.toFixed(0)}% bot-like`
            : totalFlagged > 0
              ? `${totalFlagged} bot accounts flagged`
              : `${clusters.length} clusters`}
        </span>
      </div>

      {insightsReady && primarySignal === 'canvas_hardware' ? (
        <div className="rounded-lg border-2 border-amber-500/55 bg-gradient-to-r from-amber-950/50 to-zinc-950/60 px-3 py-2.5 shadow-[0_0_22px_rgba(245,158,11,0.2)]">
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-amber-300/95">Primary signal</div>
          <p className="mt-1 text-[11px] font-semibold leading-snug text-amber-50/95">
            Canvas / hardware fingerprint — many unique IPs behind one shared fingerprint (Humanoid-class ring).
          </p>
          {primaryRationale ? <p className="mt-1 text-[10px] leading-relaxed text-amber-200/80">{primaryRationale}</p> : null}
        </div>
      ) : null}

      {sga &&
      typeof sga === 'object' &&
      sga !== null &&
      (sga as { stress_humanoid_canvas_note?: string }).stress_humanoid_canvas_note ? (
        <div className="rounded-md border border-cyan-500/30 bg-cyan-950/25 px-2.5 py-2 text-[10px] leading-snug text-cyan-100/95">
          {(sga as { stress_humanoid_canvas_note: string }).stress_humanoid_canvas_note}
        </div>
      ) : null}

      {sga &&
      typeof sga === 'object' &&
      sga !== null &&
      (sga as { forbid_email_pattern_narrative?: boolean }).forbid_email_pattern_narrative === true ? (
        <p className="rounded border border-zinc-700/80 bg-zinc-950/60 px-2 py-1.5 text-[9px] text-zinc-500">
          No <span className="font-semibold text-zinc-400">email</span> column in this file — do not claim Gmail
          dot-tricks or disposable-email rings unless the schema gains an email field.
        </p>
      ) : null}

      {spoof && typeof spoof.label === 'string' ? (
        <div className="rounded-lg border border-rose-500/35 bg-rose-950/25 px-3 py-2.5">
          <div className="text-[10px] font-bold uppercase tracking-wide text-rose-200/95">{String(spoof.label)}</div>
          {typeof spoof.rationale === 'string' ? (
            <p className="mt-1 text-[10px] leading-relaxed text-zinc-400">{spoof.rationale}</p>
          ) : null}
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] text-zinc-300">
            <dt className="text-zinc-500">Fingerprint</dt>
            <dd className="truncate font-mono text-amber-200/90">{String(spoof.dominant_fingerprint ?? '—')}</dd>
            <dt className="text-zinc-500">Accounts</dt>
            <dd className="font-semibold text-zinc-100">{String(spoof.accounts_on_dominant_fingerprint ?? '—')}</dd>
            <dt className="text-zinc-500">Distinct IPs</dt>
            <dd className="font-semibold text-amber-200">{String(spoof.distinct_ips_on_dominant_fingerprint ?? '—')}</dd>
          </dl>
        </div>
      ) : null}

      {canvasDist.length > 0 ? (
        <div className="rounded-lg border border-zinc-700/90 bg-zinc-950/40 p-3">
          <div className="mb-2 text-[9px] font-semibold uppercase tracking-wider text-amber-400/95">
            Smoking gun · fingerprint concentration
          </div>
          <div>
            <p className="mb-2 font-mono text-[10px] text-zinc-400">
              <span className="text-zinc-500">Dominant:</span>{' '}
              <span className="font-bold text-amber-200">{topCanvasFp}</span>
            </p>
            <div className="mb-1 flex justify-between text-[9px] text-zinc-500">
              <span>Share of dataset</span>
              <span className="tabular-nums text-amber-200/90">{topCanvasShare.toFixed(1)}%</span>
            </div>
            <div className="h-3 w-full overflow-hidden rounded-full bg-zinc-800">
              <div
                className="h-full rounded-full bg-gradient-to-r from-amber-500 to-amber-400 shadow-[0_0_12px_rgba(245,158,11,0.35)]"
                style={{ width: `${Math.min(100, Math.max(0, topCanvasShare))}%` }}
              />
            </div>
            <p className="mt-2 text-[10px] text-zinc-400">
              <span className="font-semibold text-zinc-200">{topCanvasRowCount}</span> rows tied to this one fingerprint
              · <span className="font-semibold text-amber-200">{topCanvasDip}</span> distinct IPs (rotation behind shared
              hardware).
            </p>
            <div className="mt-3">
              <div className="mb-1 text-center text-[8px] font-semibold uppercase tracking-wider text-zinc-600">
                IP diversity (visual)
              </div>
              <div className="relative mx-auto h-28 w-28">
                <div className="absolute inset-0 rounded-full border border-amber-500/25 bg-amber-500/5" />
                <div className="absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-amber-400/70 bg-amber-950/80 px-2 py-1.5 text-center text-[8px] font-bold leading-tight text-amber-100">
                  1
                  <br />
                  FP
                </div>
                {Array.from({ length: ipVisualDots }).map((_, i) => {
                  const angle = (i / ipVisualDots) * 2 * Math.PI - Math.PI / 2
                  const r = 46
                  const x = 56 + r * Math.cos(angle)
                  const y = 56 + r * Math.sin(angle)
                  return (
                    <div
                      key={i}
                      className="absolute h-1.5 w-1.5 rounded-full bg-rose-400/85 shadow-[0_0_6px_rgba(251,113,133,0.5)]"
                      style={{ left: `${x}px`, top: `${y}px`, transform: 'translate(-50%, -50%)' }}
                    />
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {hardwareCards.length > 0 ? (
        <div className="space-y-2">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-amber-400/95">Hardware overlap</div>
          {hardwareCards.map((card, i) => {
            const nIp = typeof card.distinct_ip_count === 'number' ? card.distinct_ip_count : null
            const nName = typeof card.distinct_name_count === 'number' ? card.distinct_name_count : null
            const acct = typeof card.accounts_in_ring === 'number' ? card.accounts_in_ring : null
            const prev =
              typeof card.canvas_fingerprint_preview === 'string' ? card.canvas_fingerprint_preview : '—'
            const summary = typeof card.summary === 'string' ? card.summary : null
            const conf = typeof card.confidence === 'string' ? card.confidence : 'high'
            return (
              <div
                key={`hw-${i}`}
                className="rounded-lg border border-amber-500/35 bg-amber-950/20 p-3 shadow-[0_0_20px_rgba(245,158,11,0.12)]"
              >
                <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wide text-amber-200/95">
                    Humanoid-class ring · {conf} confidence
                  </span>
                  {acct != null ? (
                    <span className="rounded border border-amber-600/40 px-2 py-0.5 text-[9px] text-amber-100/90">
                      {acct} accounts
                    </span>
                  ) : null}
                </div>
                <p className="mb-2 font-mono text-[10px] leading-relaxed text-amber-50/95">
                  Fingerprint <span className="font-bold text-amber-200">{prev}</span>
                </p>
                <div className="flex flex-wrap gap-3 text-[11px]">
                  {nIp != null ? (
                    <div>
                      <span className="text-zinc-500">Distinct IPs </span>
                      <span className="font-bold text-amber-200">{nIp}</span>
                    </div>
                  ) : null}
                  {nName != null ? (
                    <div>
                      <span className="text-zinc-500">Distinct names </span>
                      <span className="font-bold text-amber-200">{nName}</span>
                    </div>
                  ) : null}
                </div>
                {summary ? <p className="mt-2 text-[10px] leading-snug text-zinc-400">{summary}</p> : null}
              </div>
            )
          })}
        </div>
      ) : null}

      <div>
        <div className="mb-1 flex justify-between text-[9px] font-medium uppercase tracking-wider text-zinc-600">
          <span>{variant === 'cluster_strength' ? 'Cluster strength (bot-like density)' : 'Bot density'}</span>
          <span className="tabular-nums text-rose-200/90">{pct.toFixed(2)}%</span>
        </div>
        <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-rose-600/95 to-amber-500/90 shadow-[0_0_12px_rgba(244,63,94,0.45)]"
            style={{ width: `${pct}%` }}
          />
        </div>
        {variant === 'cluster_strength' ? (
          <div className="mt-1 text-[9px] text-zinc-500">
            Manual-like registrations ≈ <span className="font-semibold text-emerald-200/90">{manualPct.toFixed(1)}%</span>{' '}
            of cohort (100% − bot density heuristic).
          </div>
        ) : null}
        {rowCount != null ? (
          <div className="mt-1 text-[9px] text-zinc-600">
            Dataset rows <span className="text-zinc-400">{rowCount}</span> · clusters{' '}
            <span className="text-zinc-400">{clusters.length}</span>
          </div>
        ) : null}
      </div>

      {variant === 'cluster_strength' && similarityLines.length > 0 ? (
        <div className="rounded-md border border-zinc-800/80 bg-zinc-950/50 p-2.5">
          <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-violet-400/90">
            Similarity breakdown
          </div>
          <ul className="list-inside list-disc space-y-1 text-[10px] leading-relaxed text-zinc-400">
            {similarityLines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          <p className="mt-2 text-[9px] text-zinc-600">Primary cluster ranked by backend detector — raw account IDs stay in raw JSON.</p>
        </div>
      ) : null}

      {semMap && typeof semMap === 'object' && semMap !== null && 'note' in semMap ? (
        <p className="text-[9px] leading-relaxed text-zinc-600">
          <span className="font-semibold text-zinc-500">Column mapping:</span>{' '}
          {String((semMap as { note?: string }).note ?? '')}
        </p>
      ) : null}

      {workspace && isBotClusterWorkspacePayload(payload) ? (
        <button
          type="button"
          className="w-full rounded-lg border border-cyan-500/45 bg-cyan-950/40 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-cyan-100 transition-colors hover:border-cyan-400/60 hover:bg-cyan-900/35"
          onClick={() => workspace.setActiveWorkspaceData({ ...payload })}
        >
          View full list in workspace ➔
        </button>
      ) : null}
    </div>
  )
}
