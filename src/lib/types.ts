export type ChatMessage = { role: 'system' | 'user' | 'assistant'; content: string }

export type PersonaSuggestion = {
  persona_id: string
  display_name: string
  reason: string
  matching_columns: string[]
}

export type PersonaListItem = {
  id: string
  display_name: string
  recommended_tools: string[]
  suggested_queries: string[]
}

export type ChatApiResponse = {
  messages: ChatMessage[]
  debug?: Record<string, unknown>
  persona_id: string
  persona_suggestion?: PersonaSuggestion | null
}

export type CaseStatus = 'INVESTIGATING' | 'FLAGGED' | 'CLEARED'

export type CaseActivitySeries = {
  values: number[]
  threshold: number
}

export type CasesPurgeOut = { ok: boolean; cases_removed: number }

export type CaseOut = {
  id: string
  name: string
  dataset_path: string | null
  duckdb_path?: string | null
  is_active: boolean
  status: CaseStatus
  created_at?: string | null
  updated_at?: string | null
  schema_summary?: Record<string, unknown> | null
  lead_count?: number
  evidence_event_count?: number
  script_run_count?: number
  last_memory_at?: string | null
  persona_suggestion?: PersonaSuggestion | null
}

export type HealthResponse = {
  ok: boolean
  ollama_reachable: boolean
  ollama_model?: string
  ollama_env_default?: string
  ollama_using_override?: boolean
}

export type LlmPreferencesOut = {
  ollama_model: string
  env_default: string
  using_override: boolean
}

export type OllamaModelsOut = {
  models: string[]
  error?: string | null
}

export type LeadWorkflowStatus = 'OPEN' | 'VERIFIED' | 'DISMISSED' | 'ESCALATED'

export type LeadOut = {
  id: string
  case_id: string
  description: string
  severity_score: number
  raw_data_ref: Record<string, unknown> | null
  status: string
  created_at?: string | null
}

export type AuditLogOut = {
  id: number
  case_id: string
  action_taken: string
  code_executed: string | null
  agent_notes: string | null
  timestamp?: string | null
}

export type EvidenceBoardPayload = {
  leads: LeadOut[]
  audit_logs: AuditLogOut[]
}
