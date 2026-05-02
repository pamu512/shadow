import type { ReactNode } from 'react'
import { ImpossibleTravelMap } from './ImpossibleTravelMap'

type Dna = Record<string, unknown>

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v || '—'
  return String(v)
}

function topUa(dna: Dna): string {
  const arr = dna.common_user_agents
  if (!Array.isArray(arr) || arr.length === 0) return '—'
  const first = arr[0] as Record<string, unknown>
  const ua = first?.user_agent
  const c = first?.count
  return typeof ua === 'string' ? (c != null ? `${ua.slice(0, 120)}${ua.length > 120 ? '…' : ''} (${c}×)` : ua) : '—'
}

function topIsp(dna: Dna): string {
  const arr = dna.typical_isps
  if (!Array.isArray(arr) || arr.length === 0) return '—'
  const first = arr[0] as Record<string, unknown>
  const isp = first?.isp
  const c = first?.count
  return typeof isp === 'string' ? `${isp}${c != null ? ` (${c}×)` : ''}` : '—'
}

function topLoc(dna: Dna): string {
  const arr = dna.typical_login_locations
  if (!Array.isArray(arr) || arr.length === 0) return '—'
  const first = arr[0] as Record<string, unknown>
  const lat = first?.lat
  const lon = first?.lon
  if (typeof lat === 'number' && typeof lon === 'number') return `${lat.toFixed(3)}, ${lon.toFixed(3)}`
  return '—'
}

function CardShell({
  title,
  subtitle,
  children,
  highlightMismatch,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  highlightMismatch?: boolean
}) {
  return (
    <div
      className={`flex min-w-0 flex-1 flex-col rounded-lg border bg-zinc-900/80 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.04),0_0_24px_rgba(0,0,0,0.25)] backdrop-blur-md ${
        highlightMismatch ? 'border-red-500/45 ring-1 ring-red-500/25' : 'border-zinc-800/90'
      }`}
    >
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-400/85">{title}</div>
      {subtitle ? <div className="mt-0.5 text-[9px] text-zinc-600">{subtitle}</div> : null}
      <div className="mt-2 space-y-2 font-mono text-[10px] leading-relaxed text-zinc-300">{children}</div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9px] font-medium uppercase tracking-wider text-zinc-600">{label}</div>
      <div className="mt-0.5 break-words text-zinc-200">{value}</div>
    </div>
  )
}

type DiscRow = {
  field?: string
  public_label?: string
  baseline_label?: string
  baseline_value?: string
  current_value?: string
  severity?: string
}

type TravelMapPayload = {
  prior?: { lat?: number; lon?: number; label?: string }
  current?: { lat?: number; lon?: number; label?: string }
  distance_miles?: number
  elapsed_hours?: number
  implied_mph?: number
}

function ForensicTravelStrip({ tm }: { tm: TravelMapPayload }) {
  const p = tm.prior
  const c = tm.current
  if (
    !p ||
    !c ||
    typeof p.lat !== 'number' ||
    typeof p.lon !== 'number' ||
    typeof c.lat !== 'number' ||
    typeof c.lon !== 'number'
  ) {
    return null
  }
  const fmt = (lat: number, lon: number) => `${lat.toFixed(3)}, ${lon.toFixed(3)}`
  return (
    <div className="rounded-lg border border-cyan-500/35 bg-gradient-to-br from-cyan-950/25 via-zinc-950/80 to-zinc-950 p-3 font-sans shadow-[0_0_24px_rgba(6,182,212,0.08)]">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-400/90">Forensic map</div>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
        Prior session vs this login — great-circle distance and implied speed drive the impossible-travel signal.
      </p>
      <ImpossibleTravelMap
        prior={{ lat: p.lat, lon: p.lon, label: p.label }}
        current={{ lat: c.lat, lon: c.lon, label: c.label }}
      />
      <div className="mt-3 flex flex-wrap items-stretch gap-2">
        <div className="min-w-[120px] flex-1 rounded-md border border-zinc-800 bg-zinc-950/80 p-2">
          <div className="text-[9px] font-medium uppercase tracking-wider text-zinc-500">{p.label ?? 'Prior'}</div>
          <div className="mt-1 font-mono text-[11px] text-emerald-200/95">{fmt(p.lat, p.lon)}</div>
        </div>
        <div className="flex shrink-0 items-center px-1 text-lg text-cyan-500/80" aria-hidden>
          →
        </div>
        <div className="min-w-[120px] flex-1 rounded-md border border-rose-500/35 bg-rose-950/25 p-2">
          <div className="text-[9px] font-medium uppercase tracking-wider text-zinc-500">{c.label ?? 'Current'}</div>
          <div className="mt-1 font-mono text-[11px] text-rose-200/95">{fmt(c.lat, c.lon)}</div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 font-mono text-[10px] text-zinc-400">
        {tm.distance_miles != null ? (
          <span>
            <span className="text-zinc-600">Distance</span> {Number(tm.distance_miles).toLocaleString()} mi
          </span>
        ) : null}
        {tm.elapsed_hours != null ? (
          <span>
            <span className="text-zinc-600">Elapsed</span> {(Number(tm.elapsed_hours) * 60).toFixed(1)} min
          </span>
        ) : null}
        {tm.implied_mph != null ? (
          <span>
            <span className="text-zinc-600">Implied speed</span>{' '}
            <span className="font-semibold text-rose-300/95">{Number(tm.implied_mph).toFixed(0)} mph</span>
          </span>
        ) : null}
      </div>
    </div>
  )
}

type AtoVariant = 'default' | 'forensic'

export function ATODashboard({ payload, variant = 'default' }: { payload: Record<string, unknown>; variant?: AtoVariant }) {
  const baseline = (payload.historical_baseline as Record<string, unknown>) || {}
  const dna = (baseline.behavioral_dna as Dna) || {}
  const session = (payload.current_session as Record<string, unknown>) || {}
  const discrepancies = Array.isArray(payload.discrepancies) ? (payload.discrepancies as DiscRow[]) : []
  const risk = typeof payload.ato_risk_score === 'number' ? payload.ato_risk_score : null
  const safety = typeof payload.safety_score === 'number' ? payload.safety_score : null
  const fv = payload.forensic_verdict as Record<string, unknown> | undefined
  const fvHeadline = typeof fv?.headline === 'string' ? fv.headline : null
  const fvBullets = Array.isArray(fv?.bullets) ? (fv.bullets as string[]).filter((x) => typeof x === 'string') : []
  const travelMap = (payload.travel_map as TravelMapPayload | null | undefined) || null
  const userSource = typeof payload.user_id_source === 'string' ? payload.user_id_source : null
  const gauge = typeof risk === 'number' ? Math.min(100, Math.max(0, risk)) : null

  const curUa = fmt(session.user_agent)
  const curIsp = fmt(session.isp)
  const curLat = session.latitude
  const curLon = session.longitude
  const curGeo =
    typeof curLat === 'number' && typeof curLon === 'number' ? `${Number(curLat).toFixed(4)}, ${Number(curLon).toFixed(4)}` : '—'
  const curScreen = fmt(session.screen_resolution)
  const curHw = fmt(session.hardware_id)

  return (
    <div className="mt-1.5 w-full max-w-full space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/80 p-3 font-mono shadow-[0_0_32px_rgba(6,182,212,0.06)] backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800/80 pb-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500">
            {variant === 'forensic' ? 'ATO specialist' : 'Session forensics'}
          </div>
          <div className="text-xs font-semibold tracking-tight text-zinc-100">
            {variant === 'forensic' ? 'Forensic comparison · home baseline vs current session' : 'Baseline vs live telemetry'}
          </div>
        </div>
        <div className="flex flex-wrap gap-3 text-[10px]">
          {risk != null ? (
            <span className="rounded border border-rose-500/35 bg-rose-950/40 px-2 py-1 tabular-nums text-rose-200">
              ATO risk <span className="font-bold">{risk}</span>
            </span>
          ) : null}
          {safety != null ? (
            <span className="rounded border border-emerald-500/35 bg-emerald-950/35 px-2 py-1 tabular-nums text-emerald-200/90">
              Safety <span className="font-bold">{safety}</span>
            </span>
          ) : null}
          {userSource === 'schema_inferred' ? (
            <span className="rounded border border-violet-500/35 bg-violet-950/30 px-2 py-1 text-violet-200/90">
              User id auto-mapped from CSV
            </span>
          ) : null}
        </div>
      </div>

      {gauge != null ? (
        <div className="font-sans">
          <div className="text-[10px] font-medium text-zinc-500">Severity gauge · automated ATO risk</div>
          <div className="mt-1.5 h-3 w-full overflow-hidden rounded-full bg-zinc-800">
            <div
              className={`h-full rounded-full ${
                gauge >= 60
                  ? 'bg-gradient-to-r from-rose-600 to-red-500'
                  : gauge >= 35
                    ? 'bg-gradient-to-r from-amber-600 to-orange-500'
                    : 'bg-gradient-to-r from-emerald-700 to-teal-500'
              }`}
              style={{ width: `${gauge}%` }}
            />
          </div>
        </div>
      ) : null}

      {fvHeadline ? (
        <div className="rounded-lg border border-fuchsia-500/25 bg-fuchsia-950/15 px-3 py-2.5 font-sans">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-fuchsia-400/90">Forensic verdict</div>
          <p className="mt-1 text-sm font-semibold leading-snug text-zinc-100">{fvHeadline}</p>
          {fvBullets.length > 0 ? (
            <ul className="mt-2 list-inside list-disc space-y-1 text-[11px] text-zinc-400">
              {fvBullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {travelMap ? <ForensicTravelStrip tm={travelMap} /> : null}

      <div className="flex min-w-0 flex-col gap-3 md:flex-row">
        <CardShell
          title={variant === 'forensic' ? 'Home baseline' : 'Behavioral baseline'}
          subtitle={variant === 'forensic' ? 'Historical DNA — trusted cohort' : 'Historical DNA (DuckDB cohort)'}
        >
          <Row label="Top user agent" value={topUa(dna)} />
          <Row label="Typical ISP / org" value={topIsp(dna)} />
          <Row label="Usual geo (lat, lon)" value={topLoc(dna)} />
          <Row label="Historical events" value={fmt(baseline.historical_event_count)} />
        </CardShell>
        <CardShell
          title={variant === 'forensic' ? 'Current session' : 'Live session'}
          subtitle={variant === 'forensic' ? 'Live telemetry under investigation' : 'Current claim / hijack window'}
          highlightMismatch={variant === 'forensic' && risk != null && risk >= 45}
        >
          <Row label="User agent" value={curUa} />
          <Row label="ISP / org" value={curIsp} />
          <Row label="Geo (lat, lon)" value={curGeo} />
          <Row label="Screen" value={curScreen} />
          <Row label="Hardware id" value={curHw} />
        </CardShell>
      </div>

      {discrepancies.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-zinc-800/90 bg-[#08080a]/90">
          <div className="border-b border-zinc-800 bg-zinc-950/80 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-amber-400/90">
            Discrepancy matrix
          </div>
          <div className="max-h-[min(40vh,320px)] overflow-auto">
            <table className="w-full border-collapse text-left text-[10px]">
              <thead className="sticky top-0 z-10 bg-zinc-900/95">
                <tr className="border-b border-zinc-800">
                  <th className="px-3 py-2 font-semibold text-zinc-500">Signal</th>
                  <th className="px-3 py-2 font-semibold text-zinc-500">Baseline</th>
                  <th className="px-3 py-2 font-semibold text-zinc-500">Current</th>
                  <th className="px-3 py-2 font-semibold text-zinc-500">Severity</th>
                </tr>
              </thead>
              <tbody>
                {discrepancies.map((d, i) => {
                  const sev = String(d.severity ?? '').toLowerCase()
                  const hot = sev === 'high' || sev === 'critical'
                  return (
                    <tr key={i} className="border-b border-zinc-800/60 hover:bg-zinc-900/40">
                      <td className="px-3 py-2 align-top text-zinc-200">
                        {d.public_label ? (
                          <>
                            <span className="font-medium text-zinc-100">{d.public_label}</span>
                            <div className="mt-0.5 font-mono text-[9px] text-zinc-600">{String(d.field ?? '—')}</div>
                          </>
                        ) : (
                          <span className="text-zinc-300">{String(d.field ?? d.baseline_label ?? '—')}</span>
                        )}
                      </td>
                      <td className="max-w-[200px] px-3 py-2 align-top break-words text-zinc-500">{String(d.baseline_value ?? '—')}</td>
                      <td
                        className={`max-w-[220px] px-3 py-2 align-top break-words ${
                          hot ? 'font-semibold text-red-400' : 'text-zinc-200'
                        }`}
                      >
                        {String(d.current_value ?? '—')}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 align-top uppercase text-zinc-500">{sev || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  )
}
