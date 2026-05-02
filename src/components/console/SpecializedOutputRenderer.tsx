import type { ReactNode } from 'react'
import { ATODashboard } from './specialized/ATODashboard'
import { BotClusterView } from './specialized/BotClusterView'
import { BotHardwareForensicCard } from './specialized/BotHardwareForensicCard'
import { CrossCaseHitsView } from './specialized/CrossCaseHitsView'
import { DisputeCard } from './specialized/DisputeCard'
import { ForensicVerdictCard } from './specialized/ForensicVerdictCard'
import { NetworkGraphSummary } from './specialized/NetworkGraphSummary'
import { GlobalLinkageView } from './specialized/GlobalLinkageView'

export type SpecializedOutputKind =
  | 'ato'
  | 'bot'
  | 'bot_hardware'
  | 'dispute'
  | 'network'
  | 'cross_case'
  | 'global_linkage'
  | 'forensic_verdict'

export function getOutputKind(payload: Record<string, unknown>): SpecializedOutputKind | null {
  if (payload.kind === 'forensic_verdict_card') return 'forensic_verdict'
  if (
    payload.kind === 'bot_hardware_forensic' &&
    payload.hardware_ip_forensics &&
    typeof payload.hardware_ip_forensics === 'object'
  ) {
    return 'bot_hardware'
  }
  const gl = payload.global_linkage
  if (
    gl &&
    typeof gl === 'object' &&
    Array.isArray((gl as { timeline?: unknown }).timeline) &&
    ((gl as { timeline: unknown[] }).timeline as unknown[]).length > 0
  ) {
    return 'global_linkage'
  }
  if (payload.kind === 'cross_case_matches') return 'cross_case'
  if ('geo_mismatch' in payload || 'travel_velocity' in payload) return 'ato'
  if (typeof payload.ato_risk_score === 'number' && (payload.historical_baseline != null || payload.current_session != null)) {
    return 'ato'
  }
  const disc = payload.discrepancies
  if (Array.isArray(disc) && disc.length > 0 && payload.current_session != null) return 'ato'

  const hwCards = payload.hardware_overlap_cards
  const canvasDist = payload.canvas_fingerprint_distribution
  if (
    typeof payload.bot_density_pct === 'number' ||
    (Array.isArray(payload.clusters) && (payload.clusters as unknown[]).length > 0) ||
    (Array.isArray(hwCards) && hwCards.length > 0 && payload.ok !== false) ||
    (Array.isArray(canvasDist) && canvasDist.length > 0 && payload.ok !== false) ||
    (payload.hardware_spoofing_assessment != null && payload.ok !== false)
  ) {
    return 'bot'
  }

  if ('evidence_manifest' in payload || 'chargeback_risk' in payload || typeof payload.chargeback_risk_score === 'number') {
    return 'dispute'
  }

  if ('graph_nodes' in payload && Array.isArray(payload.graph_nodes)) return 'network'
  const gd = payload.graph_data
  if (gd && typeof gd === 'object' && gd !== null && 'nodes' in gd) return 'network'

  return null
}

/** Dispatcher: persona-style UI for known tool / execution JSON shapes. */
export function getComponentForOutput(payload: Record<string, unknown>, _toolName?: string): ReactNode {
  const kind = getOutputKind(payload)
  const agentType = typeof payload.agent_type === 'string' ? payload.agent_type : null
  switch (kind) {
    case 'ato':
      return <ATODashboard payload={payload} variant={agentType === 'ato' ? 'forensic' : 'default'} />
    case 'bot_hardware':
      return <BotHardwareForensicCard payload={payload} />
    case 'bot':
      return <BotClusterView payload={payload} variant={agentType === 'bot' ? 'cluster_strength' : 'default'} />
    case 'forensic_verdict':
      return <ForensicVerdictCard payload={payload} />
    case 'dispute':
      return (
        <DisputeCard
          payload={payload}
          layout={agentType === 'chargeback' ? 'evidence_checklist' : 'letter'}
        />
      )
    case 'network':
      return <NetworkGraphSummary payload={payload} />
    case 'cross_case':
      return <CrossCaseHitsView payload={payload} />
    case 'global_linkage':
      return <GlobalLinkageView payload={payload} />
    default:
      return null
  }
}
