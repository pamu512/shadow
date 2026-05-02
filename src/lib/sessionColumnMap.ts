const STORAGE_KEY = 'shadow:session-column-map-v1'

export type SessionColumnMapping = {
  /** Logical role (e.g. user_id). */
  role: string
  /** Actual CSV / DuckDB column the operator confirmed. */
  sourceColumn: string
  updatedAt: number
}

type Store = Record<string, SessionColumnMapping>

function readAll(): Store {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const p = JSON.parse(raw) as unknown
    return p && typeof p === 'object' && !Array.isArray(p) ? (p as Store) : {}
  } catch {
    return {}
  }
}

function writeAll(s: Store) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s))
  } catch {
    /* ignore */
  }
}

export function getSessionColumnMapping(caseId: string | null | undefined): SessionColumnMapping | null {
  if (!caseId) return null
  const m = readAll()[caseId]
  return m && typeof m.sourceColumn === 'string' ? m : null
}

export function setSessionUserIdColumn(caseId: string, sourceColumn: string, role = 'user_id') {
  const all = readAll()
  all[caseId] = { role, sourceColumn, updatedAt: Date.now() }
  writeAll(all)
}

export function clearSessionColumnMapping(caseId: string) {
  const all = readAll()
  delete all[caseId]
  writeAll(all)
}

/** Clear browser session hints for every case (e.g. after purge-all). */
export function clearAllSessionColumnMappings() {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

/** Prefix every outbound user message so the agent keeps the mapping for this case. */
export function columnMappingPreamble(caseId: string | null | undefined): string {
  const m = getSessionColumnMapping(caseId)
  if (!m) return ''
  return (
    `[session column map] For case tools, treat CSV column "${m.sourceColumn}" as the account identifier ` +
    `(logical ${m.role}). Use it in user_column / user_id_column arguments where the schema uses a different name.\n\n`
  )
}
