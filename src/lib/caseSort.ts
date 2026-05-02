import type { CaseOut, CaseStatus } from './types'

const STATUS_RANK: Record<CaseStatus, number> = {
  FLAGGED: 0,
  INVESTIGATING: 1,
  CLEARED: 2,
}

/** FLAGGED first, then INVESTIGATING, then CLEARED; tie-break by created_at desc. */
export function sortCasesByStatus(cases: CaseOut[]): CaseOut[] {
  return [...cases].sort((a, b) => {
    const ra = STATUS_RANK[a.status] ?? 9
    const rb = STATUS_RANK[b.status] ?? 9
    if (ra !== rb) return ra - rb
    const ta = a.created_at ? new Date(a.created_at).getTime() : 0
    const tb = b.created_at ? new Date(b.created_at).getTime() : 0
    return tb - ta
  })
}

export function coerceCaseStatus(raw: string | null | undefined): CaseStatus {
  if (raw === 'FLAGGED' || raw === 'CLEARED' || raw === 'INVESTIGATING') return raw
  return 'INVESTIGATING'
}
