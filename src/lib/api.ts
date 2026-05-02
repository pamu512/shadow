import { invoke } from '@tauri-apps/api/core'
import type {
  CaseActivitySeries,
  CaseOut,
  CasesPurgeOut,
  CaseStatus,
  ChatApiResponse,
  ChatMessage,
  EvidenceBoardPayload,
  HealthResponse,
  LlmPreferencesOut,
  OllamaModelsOut,
  LeadOut,
  LeadWorkflowStatus,
  PersonaListItem,
} from './types'

export async function getApiBase(): Promise<string> {
  try {
    return await invoke<string>('get_api_base_url')
  } catch {
    return import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8742'
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const base = (await getApiBase()).replace(/\/+$/, '')
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const t = await res.text()
    throw new Error(t || res.statusText)
  }
  return res.json() as Promise<T>
}

export const AGENT_INJECT_EVENT = 'shadow:agent-inject' as const

export type AgentInjectDetail = { text: string; persona_id?: string | null }

export async function getEvidenceWsUrl(caseId: string): Promise<string> {
  const base = await getApiBase()
  const u = new URL(base)
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
  u.pathname = `/ws/cases/${caseId}/evidence`
  u.hash = ''
  return u.toString()
}

export async function fetchCasesActivityBulk(caseIds: string[]): Promise<Record<string, CaseActivitySeries>> {
  if (caseIds.length === 0) return {}
  const res = await apiFetch<{ activities: Record<string, CaseActivitySeries> }>('/api/cases/activity-bulk', {
    method: 'POST',
    body: JSON.stringify({ case_ids: caseIds }),
  })
  return res.activities
}

export async function fetchHealth(): Promise<HealthResponse> {
  return apiFetch('/health')
}

export async function fetchOllamaModelTags(): Promise<OllamaModelsOut> {
  return apiFetch('/ollama-models')
}

async function apiFetchWithNotFoundFallback<T>(paths: [string, string], init?: RequestInit): Promise<T> {
  let last: unknown
  for (const path of paths) {
    try {
      return await apiFetch<T>(path, init)
    } catch (e) {
      last = e
      const msg = e instanceof Error ? e.message : String(e)
      if (!msg.includes('Not Found')) throw e
    }
  }
  throw last
}

export async function fetchLlmPreferences(): Promise<LlmPreferencesOut> {
  return apiFetchWithNotFoundFallback(['/llm-preferences', '/api/preferences/llm'])
}

export async function patchLlmPreferences(body: { ollama_model: string | null }): Promise<LlmPreferencesOut> {
  return apiFetchWithNotFoundFallback<LlmPreferencesOut>(['/llm-preferences', '/api/preferences/llm'], {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function fetchCases(): Promise<CaseOut[]> {
  return apiFetch('/api/cases')
}

export async function deleteCase(caseId: string): Promise<void> {
  const base = (await getApiBase()).replace(/\/+$/, '')
  const res = await fetch(`${base}/api/cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' })
  if (!res.ok) {
    const t = await res.text()
    throw new Error(t || res.statusText)
  }
}

export async function purgeAllCases(): Promise<CasesPurgeOut> {
  const base = (await getApiBase()).replace(/\/+$/, '')
  let res = await fetch(`${base}/api/cases/purge-all`, { method: 'DELETE' })
  if (res.status === 405) {
    res = await fetch(`${base}/api/cases/purge-all`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
  }
  if (!res.ok) {
    const t = await res.text()
    throw new Error(t || res.statusText)
  }
  return res.json() as Promise<CasesPurgeOut>
}

export async function fetchPersonas(): Promise<PersonaListItem[]> {
  return apiFetch<PersonaListItem[]>('/api/personas')
}

export async function createCase(
  name: string,
  datasetPath?: string,
  status: CaseStatus = 'INVESTIGATING',
): Promise<CaseOut> {
  return apiFetch('/api/cases', {
    method: 'POST',
    body: JSON.stringify({ name, dataset_path: datasetPath || null, status }),
  })
}

/** Multipart upload: copies CSV to durable storage and builds DuckDB + schema summary. */
export async function uploadCaseWithProgress(
  name: string,
  file: File,
  status: CaseStatus,
  onProgress: (pct: number) => void,
): Promise<CaseOut> {
  const base = await getApiBase()
  const fd = new FormData()
  fd.append('name', name)
  fd.append('status', status)
  fd.append('file', file)
  onProgress(2)
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${base}/api/cases/upload`)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) {
        onProgress(Math.min(90, Math.round((e.loaded / e.total) * 90)))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100)
        resolve(xhr.response as CaseOut)
        return
      }
      let msg = xhr.statusText
      const r = xhr.response
      if (r && typeof r === 'object' && r !== null && 'detail' in r) {
        const d = (r as { detail: unknown }).detail
        if (typeof d === 'string') msg = d
        else if (Array.isArray(d))
          msg = d.map((x: { msg?: string }) => (typeof x === 'object' && x && 'msg' in x ? String(x.msg) : JSON.stringify(x))).join('; ')
        else msg = JSON.stringify(d)
      } else if (typeof r === 'string' && r) msg = r
      reject(new Error(msg))
    }
    xhr.onerror = () => reject(new Error('Network error during upload'))
    xhr.send(fd)
  })
}

export async function patchCase(
  id: string,
  body: { status?: CaseStatus; name?: string },
): Promise<CaseOut> {
  return apiFetch(`/api/cases/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function activateCase(id: string): Promise<CaseOut> {
  return apiFetch(`/api/cases/${id}/activate`, { method: 'POST', body: '{}' })
}

export async function fetchWarehouseOverlap(
  entityId: string,
  entityType: string,
  excludeCaseId?: string | null,
): Promise<Record<string, unknown>> {
  const q = new URLSearchParams({
    entity_id: entityId.trim(),
    entity_type: entityType.trim(),
  })
  if (excludeCaseId) q.set('exclude_case_id', excludeCaseId)
  return apiFetch<Record<string, unknown>>(`/api/warehouse/overlap?${q.toString()}`)
}

export async function previewCase(id: string, rows = 50): Promise<{ columns: string[]; rows: Record<string, unknown>[] }> {
  const base = await getApiBase()
  const res = await fetch(`${base}/api/cases/${id}/preview?rows=${rows}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function analyzeChargebackCase(caseId: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/chargeback/analyze`, {
    method: 'POST',
    body: '{}',
  })
}

export async function fetchRepresentmentManifest(caseId: string, transactionId: string): Promise<Record<string, unknown>> {
  const q = new URLSearchParams({ transaction_id: transactionId })
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/chargeback/manifest?${q}`)
}

export async function downloadRepresentmentPackage(caseId: string, transactionId: string): Promise<Blob> {
  const base = await getApiBase()
  const q = new URLSearchParams({ transaction_id: transactionId })
  const res = await fetch(`${base}/api/cases/${caseId}/chargeback/package.zip?${q}`)
  if (!res.ok) throw new Error(await res.text())
  return res.blob()
}

export async function simulateRepresentment(
  caseId: string,
  transactionId?: string | null,
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/chargeback/simulate-representment`, {
    method: 'POST',
    body: JSON.stringify({ transaction_id: transactionId?.trim() || null }),
  })
}

export async function fetchAtoProfile(
  caseId: string,
  userId: string,
  userColumn?: string | null,
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/ato/profile`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, user_column: userColumn?.trim() || null }),
  })
}

export async function analyzeAtoSession(
  caseId: string,
  userId: string | null | undefined,
  currentSession: Record<string, unknown>,
  userColumn?: string | null,
): Promise<Record<string, unknown>> {
  const uid = typeof userId === 'string' ? userId.trim() : ''
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/ato/analyze`, {
    method: 'POST',
    body: JSON.stringify({
      user_id: uid || null,
      current_session: currentSession,
      user_column: userColumn?.trim() || null,
    }),
  })
}

export async function fetchAtoUserIdSamples(
  caseId: string,
  limit = 40,
): Promise<{
  ok: boolean
  column?: string | null
  user_ids?: string[]
  samples?: { user_id: string; row_count: number }[]
  error?: string
  columns?: string[]
}> {
  const q = new URLSearchParams({ limit: String(limit) })
  return apiFetch(`/api/cases/${caseId}/ato/user-id-samples?${q}`)
}

export async function killAtoSession(
  caseId: string,
  userId: string,
  opts?: { sessionId?: string | null; reason?: string | null },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/ato/kill-session`, {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      session_id: opts?.sessionId ?? null,
      reason: opts?.reason ?? null,
    }),
  })
}

export async function detectBotClusters(caseId: string): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/bots/detect`, {
    method: 'POST',
    body: '{}',
  })
}

export async function bulkSuspendBotCluster(
  caseId: string,
  body: { account_ids: string[]; reason?: string; cluster_id?: string | null },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/bots/bulk-suspend`, {
    method: 'POST',
    body: JSON.stringify({
      account_ids: body.account_ids,
      reason: body.reason ?? 'BOT_CLUSTER_SUSPEND',
      cluster_id: body.cluster_id ?? null,
    }),
  })
}

export async function fetchFraudNetworkRings(
  caseId: string,
  opts?: {
    account_column?: string | null
    payer_column?: string | null
    payee_column?: string | null
    amount_column?: string | null
  },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/cases/${caseId}/network/rings`, {
    method: 'POST',
    body: JSON.stringify({
      account_column: opts?.account_column?.trim() || null,
      payer_column: opts?.payer_column?.trim() || null,
      payee_column: opts?.payee_column?.trim() || null,
      amount_column: opts?.amount_column?.trim() || null,
    }),
  })
}

/** GEXF / GraphML for Gephi, Cytoscape, etc. (full graph, not UI-trimmed). */
export async function downloadFraudRingNetworkExport(
  caseId: string,
  format: 'gexf' | 'graphml',
  opts?: {
    account_column?: string | null
    payer_column?: string | null
    payee_column?: string | null
    amount_column?: string | null
  },
): Promise<Blob> {
  const base = await getApiBase()
  const res = await fetch(`${base}/api/cases/${caseId}/network/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      export_format: format,
      account_column: opts?.account_column?.trim() || null,
      payer_column: opts?.payer_column?.trim() || null,
      payee_column: opts?.payee_column?.trim() || null,
      amount_column: opts?.amount_column?.trim() || null,
    }),
  })
  if (!res.ok) {
    const t = await res.text()
    throw new Error(t || res.statusText)
  }
  return res.blob()
}

export async function fetchEvidenceBoard(caseId: string): Promise<EvidenceBoardPayload> {
  return apiFetch<EvidenceBoardPayload>(`/api/cases/${caseId}/evidence`)
}

export async function patchLead(caseId: string, leadId: string, status: LeadWorkflowStatus): Promise<LeadOut> {
  return apiFetch<LeadOut>(`/api/cases/${caseId}/leads/${leadId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}

export async function sendChat(
  messages: ChatMessage[],
  caseId?: string | null,
  personaId?: string | null,
  threadReset?: boolean,
): Promise<ChatApiResponse> {
  return apiFetch<ChatApiResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      messages,
      case_id: caseId ?? null,
      persona_id: personaId ?? null,
      thread_reset: Boolean(threadReset),
    }),
  })
}

export async function codeReview(script: string, language: 'python' | 'r', caseId?: string | null) {
  return apiFetch<{ original: string; suggested: string; notes: string }>('/api/code-review', {
    method: 'POST',
    body: JSON.stringify({ script, language, case_id: caseId ?? null }),
  })
}

export async function executeCode(language: 'python' | 'r', code: string, caseId?: string | null) {
  return apiFetch<{
    stdout: string
    stderr: string
    exit_code: number
    plots_base64: string[]
    violations?: string[]
  }>('/api/execute', {
    method: 'POST',
    body: JSON.stringify({ language, code, case_id: caseId ?? null }),
  })
}

export async function optimizeThresholds(
  model: 'isolation_forest' | 'random_forest',
  caseId?: string | null,
  targetColumn?: string | null,
) {
  return apiFetch<{
    thresholds: Record<string, unknown>
    optimization_manifest: Record<string, unknown>
    metrics_at_threshold: Record<string, unknown>
    optimization_objective: string
  }>('/api/optimize-thresholds', {
    method: 'POST',
    body: JSON.stringify({
      model,
      case_id: caseId ?? null,
      target_column: targetColumn ?? null,
    }),
  })
}

export async function scaffoldCode(language: 'python' | 'r', intent: string, caseId?: string | null) {
  return apiFetch<{ code: string; explanation: string }>('/api/scaffold', {
    method: 'POST',
    body: JSON.stringify({ language, intent, case_id: caseId ?? null }),
  })
}
