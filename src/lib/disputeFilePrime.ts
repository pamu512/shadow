/** Heuristic extraction of transaction / order identifiers from dispute text (PDF bytes as Latin-1 or plain .txt). */

const TXN_RULES: { re: RegExp; group?: number }[] = [
  { re: /transaction\s*(?:id|#|number|no\.?)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9_-]{5,40})/gi, group: 1 },
  { re: /order\s*(?:id|#|number)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9_-]{5,40})/gi, group: 1 },
  { re: /txn\s*(?:id|#)?\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9_-]{5,40})/gi, group: 1 },
  { re: /\b(?:chb|cb)-[A-Z0-9]{6,24}\b/gi },
  { re: /\b(?:ord|txn)[_-][A-Z0-9]{8,32}\b/gi },
]

function uniq(ids: string[], limit: number): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of ids) {
    const s = raw.trim()
    if (s.length < 6 || s.length > 48) continue
    const k = s.toLowerCase()
    if (seen.has(k)) continue
    seen.add(k)
    out.push(s)
    if (out.length >= limit) break
  }
  return out
}

export function extractTransactionIdCandidates(text: string, limit = 8): string[] {
  const found: string[] = []
  for (const { re, group } of TXN_RULES) {
    const r = new RegExp(re.source, 'gi')
    let m: RegExpExecArray | null
    while ((m = r.exec(text)) !== null) {
      const cap = group != null ? m[group] : m[0]
      if (cap) found.push(String(cap).replace(/^[:#\s]+/, '').trim())
    }
  }
  return uniq(found, limit)
}

/** Same patterns as `extractTransactionIdCandidates`; named for co-pilot / drop-zone flows. */
export function heuristicIdExtractor(text: string, limit = 8): string[] {
  return extractTransactionIdCandidates(text, limit)
}

export function latin1FromArrayBuffer(buf: ArrayBuffer, maxChars = 1_200_000): string {
  const u8 = new Uint8Array(buf)
  const n = Math.min(u8.length, maxChars)
  let s = ''
  for (let i = 0; i < n; i++) s += String.fromCharCode(u8[i])
  return s
}
