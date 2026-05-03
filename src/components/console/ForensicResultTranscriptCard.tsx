import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Pin } from 'lucide-react'
import type { PinnedForensicPayload } from '../../lib/types'
import { GhostButton } from '../ui/ForensicChrome'
import { getComponentForOutput, getOutputKind } from './SpecializedOutputRenderer'
import { renderTextWithEntityChips } from './EntityChip'

export type { PinnedForensicPayload }

type Props = {
  payload: Record<string, unknown>
  onPin?: (item: PinnedForensicPayload) => void
}

function tierFromPayload(payload: Record<string, unknown>): 'CRITICAL' | 'SUSPICIOUS' | 'CLEAR' {
  const verdictRaw = typeof payload.verdict === 'string' ? payload.verdict.toUpperCase() : ''
  if (verdictRaw.includes('CRITICAL') || verdictRaw.includes('SEVERE')) return 'CRITICAL'
  if (verdictRaw.includes('SUSPICIOUS') || verdictRaw.includes('WARN') || verdictRaw.includes('HIGH')) {
    return 'SUSPICIOUS'
  }
  const risk =
    typeof payload.ato_risk_score === 'number'
      ? payload.ato_risk_score
      : typeof payload.risk_score === 'number'
        ? payload.risk_score
        : typeof payload.chargeback_risk_score === 'number'
          ? payload.chargeback_risk_score
          : null
  if (risk == null) return 'CLEAR'
  if (risk >= 55) return 'CRITICAL'
  if (risk >= 30) return 'SUSPICIOUS'
  return 'CLEAR'
}

function hardwareIpRatioLine(payload: Record<string, unknown>): string | null {
  const hw = payload.hardware_ip_forensics as Record<string, unknown> | undefined
  if (!hw) return null
  const ua = Number(hw.unique_accounts_on_dominant)
  const di = Number(hw.unique_ips_on_dominant)
  if (!Number.isFinite(ua) || !Number.isFinite(di) || ua <= 0 || di <= 0) return null
  const ratio = (ua / di).toFixed(2)
  return `${ratio}:1 account-to-IP ratio on dominant hardware fingerprint (smoking-gun Humanoid signal)`
}

function primarySignal(payload: Record<string, unknown>): string | null {
  const hwLine = hardwareIpRatioLine(payload)
  if (hwLine) return hwLine
  const fv = payload.forensic_verdict as Record<string, unknown> | undefined
  if (fv && typeof fv.headline === 'string') return fv.headline
  const flags = payload.flags as { public_label?: string; detail?: string }[] | undefined
  if (Array.isArray(flags) && flags[0]) {
    return flags[0].public_label || flags[0].detail || null
  }
  if (typeof payload.verdict_label === 'string') return payload.verdict_label
  if (typeof payload.verdict === 'string') return payload.verdict
  const hw = payload.hardware_ip_forensics as { infrastructure_summary?: string } | undefined
  if (hw?.infrastructure_summary) return String(hw.infrastructure_summary).slice(0, 160)
  return null
}

function riskGaugePct(payload: Record<string, unknown>): number | null {
  if (typeof payload.ato_risk_score === 'number') return Math.min(100, Math.max(0, payload.ato_risk_score))
  if (typeof payload.risk_score === 'number') return Math.min(100, Math.max(0, payload.risk_score))
  if (typeof payload.chargeback_risk_score === 'number') return Math.min(100, Math.max(0, payload.chargeback_risk_score))
  const fv = payload.forensic_verdict as Record<string, unknown> | undefined
  if (fv && typeof fv.risk_gauge_0_100 === 'number') return Math.min(100, Math.max(0, Number(fv.risk_gauge_0_100)))
  return null
}

function summaryLine(payload: Record<string, unknown>): string {
  const parts: string[] = []
  if (typeof payload.user_id === 'string') parts.push(`User ${payload.user_id}`)
  if (typeof payload.user_id_source === 'string' && payload.user_id_source === 'schema_inferred') {
    parts.push('auto-mapped id')
  }
  if (typeof payload.ato_risk_score === 'number') parts.push(`ATO risk ${payload.ato_risk_score}`)
  if (typeof payload.safety_score === 'number') parts.push(`Safety ${payload.safety_score}`)
  if (typeof payload.chargeback_risk_score === 'number') parts.push(`Chargeback risk ${payload.chargeback_risk_score}`)
  return parts.join(' · ') || 'Structured forensic payload'
}

export function ForensicResultTranscriptCard({ payload, onPin }: Props) {
  const tier = tierFromPayload(payload)
  const [deepOpen, setDeepOpen] = useState(false)
  const gauge = useMemo(() => riskGaugePct(payload), [payload])
  const deepKind = getOutputKind(payload)
  const deepPanel = deepKind ? getComponentForOutput(payload) : null

  const headerClass =
    tier === 'CRITICAL'
      ? 'border-rose-600/55 bg-gradient-to-r from-rose-950/90 to-red-950/70 text-rose-50'
      : tier === 'SUSPICIOUS'
        ? 'border-amber-500/50 bg-gradient-to-r from-amber-950/85 to-zinc-900/80 text-amber-50'
        : 'border-emerald-600/40 bg-gradient-to-r from-emerald-950/50 to-zinc-900/70 text-emerald-50'

  const primary = primarySignal(payload)

  const onPinClick = () => {
    if (!onPin) return
    onPin({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      title:
        tier === 'CRITICAL' ? 'Critical forensic signal' : tier === 'SUSPICIOUS' ? 'Suspicious signal' : 'Forensic result',
      subtitle: summaryLine(payload),
      payload,
      pinnedAt: Date.now(),
    })
  }

  return (
    <div className="my-2 w-full max-w-full overflow-hidden rounded-xl border border-zinc-800 bg-[#0d0d0d] font-sans shadow-[0_0_32px_rgba(0,0,0,0.45)]">
      <div className={`flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2.5 ${headerClass}`}>
        <div className="flex items-center gap-2">
          <span className="rounded border border-white/15 bg-black/25 px-2 py-0.5 font-mono text-[10px] font-bold tracking-widest">
            {tier}
          </span>
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/90">Forensic verdict</span>
        </div>
        {onPin ? (
          <GhostButton
            type="button"
            onClick={onPinClick}
            className="!border-white/20 !bg-black/20 !py-1 !text-[10px] text-white/90 hover:!bg-black/35"
            title="Pin to Active Leads rail"
          >
            <Pin className="mr-1 inline h-3 w-3" aria-hidden />
            Pin
          </GhostButton>
        ) : null}
      </div>

      {gauge != null ? (
        <div className="border-b border-zinc-800/80 bg-zinc-950/40 px-3 py-2">
          <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-zinc-500">Severity gauge</div>
          <div className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-zinc-900">
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
          <div className="mt-1 text-right font-mono text-[11px] font-semibold tabular-nums text-rose-200/95">{gauge.toFixed(1)}%</div>
        </div>
      ) : null}

      {primary ? (
        <div className="border-b border-zinc-800/90 bg-zinc-950/50 px-3 py-2.5">
          <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-zinc-500">Primary signal</div>
          <p className="mt-1 text-sm font-semibold leading-snug text-zinc-100">{renderTextWithEntityChips(primary)}</p>
        </div>
      ) : null}
      <div className="px-3 py-2 text-[11px] leading-relaxed text-zinc-400">
        {renderTextWithEntityChips(summaryLine(payload))}
      </div>

      {deepPanel ? (
        <div className="border-t border-zinc-800/80 bg-zinc-950/30">
          <button
            type="button"
            onClick={() => setDeepOpen((o) => !o)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-zinc-500 transition-colors hover:bg-zinc-900/50 hover:text-zinc-300"
          >
            {deepOpen ? <ChevronDown className="h-3.5 w-3.5" aria-hidden /> : <ChevronRight className="h-3.5 w-3.5" aria-hidden />}
            Full forensic panel
          </button>
          {deepOpen ? <div className="border-t border-zinc-800/60 px-1 pb-2">{deepPanel}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
