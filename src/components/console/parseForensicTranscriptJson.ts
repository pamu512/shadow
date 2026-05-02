/** Detect assistant messages that are pure JSON forensic payloads (not [tool …] lines). */
export function parseForensicTranscriptJson(text: string): Record<string, unknown> | null {
  let t = text.trim()
  const fence = /^```(?:json)?\s*\n([\s\S]*?)\n```\s*$/i.exec(t)
  if (fence) t = fence[1].trim()
  if (!t.startsWith('{') || t.includes('[tool')) return null
  try {
    const o = JSON.parse(t) as unknown
    if (!o || typeof o !== 'object' || Array.isArray(o)) return null
    const rec = o as Record<string, unknown>
    const fv = rec.forensic_verdict
    const hasFv = typeof fv === 'object' && fv !== null
    if (typeof rec.verdict === 'string') return rec
    if (typeof rec.verdict_label === 'string') return rec
    if (hasFv) return rec
    if (typeof rec.headline === 'string' && typeof rec.risk_gauge_0_100 === 'number') return rec
    if (rec.ok === true && typeof rec.ato_risk_score === 'number' && rec.historical_baseline) return rec
    if (rec.ok === true && typeof rec.chargeback_risk_score === 'number') return rec
    return null
  } catch {
    return null
  }
}
