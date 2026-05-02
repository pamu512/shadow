import type { ReactNode } from 'react'

type Tier = 'critical' | 'suspicious' | 'clear'

function tierFromPayload(payload: Record<string, unknown>): Tier {
  const hw = payload.hardware_ip_forensics as Record<string, unknown> | undefined
  if (hw?.critical_hardware_spoofing === true) return 'critical'
  const v = typeof payload.verdict === 'string' ? payload.verdict.toUpperCase() : ''
  if (v.includes('CRITICAL') || v.includes('SEVERE')) return 'critical'
  if (v.includes('SUSPICIOUS') || v.includes('HIGH')) return 'suspicious'
  const risk =
    typeof payload.ato_risk_score === 'number'
      ? payload.ato_risk_score
      : typeof payload.bot_density_pct === 'number'
        ? payload.bot_density_pct
        : null
  if (risk != null && risk >= 55) return 'critical'
  if (risk != null && risk >= 30) return 'suspicious'
  return 'clear'
}

function hwRatioHeadline(payload: Record<string, unknown>): string | null {
  const hw = payload.hardware_ip_forensics as Record<string, unknown> | undefined
  if (!hw) return null
  const ua = Number(hw.unique_accounts_on_dominant)
  const di = Number(hw.unique_ips_on_dominant)
  if (!Number.isFinite(ua) || !Number.isFinite(di) || ua <= 0 || di <= 0) return null
  const ratio = (ua / di).toFixed(2)
  return `${ratio}:1 HW·TO·IP RATIO DETECTED`
}

function defaultHeadline(toolName: string, payload: Record<string, unknown>, ok: boolean): string {
  if (!ok) return 'Execution risk'
  const hw = hwRatioHeadline(payload)
  if (hw) return hw
  const bd = payload.bot_density_pct
  if (typeof bd === 'number') return `Bot density ${bd.toFixed(1)}%`
  const ar = payload.ato_risk_score
  if (typeof ar === 'number') return `ATO risk ${ar.toFixed(0)} / 100`
  return toolName.replace(/_tool$/i, '').replace(/_/g, ' ')
}

const tierStyle: Record<Tier, string> = {
  critical: 'border-rose-500/55 bg-gradient-to-r from-rose-950/90 to-red-950/50 text-rose-50',
  suspicious: 'border-amber-500/50 bg-gradient-to-r from-amber-950/80 to-orange-950/40 text-amber-50',
  clear: 'border-emerald-500/40 bg-gradient-to-r from-emerald-950/50 to-zinc-950/80 text-emerald-50',
}

export function ToolVerdictRibbon({
  toolName,
  payload,
  ok,
  rightSlot,
}: {
  toolName: string
  payload: Record<string, unknown>
  ok: boolean
  rightSlot?: ReactNode
}) {
  const tier = ok ? tierFromPayload(payload) : 'critical'
  const headline = defaultHeadline(toolName, payload, ok)
  const emoji = !ok ? '⚠️' : tier === 'critical' ? '🚨' : tier === 'suspicious' ? '⚡' : '✓'

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2.5 font-sans ${tierStyle[tier]}`}
    >
      <div className="min-w-0">
        <div className="text-[9px] font-semibold uppercase tracking-[0.2em] opacity-90">Forensic verdict</div>
        <div className="mt-0.5 truncate text-sm font-bold tracking-tight">
          <span className="mr-1.5" aria-hidden>
            {emoji}
          </span>
          {headline}
        </div>
      </div>
      {rightSlot ? <div className="shrink-0">{rightSlot}</div> : null}
    </div>
  )
}
