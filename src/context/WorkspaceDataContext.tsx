import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

export type ActiveWorkspaceData = Record<string, unknown> | null

export function isBotClusterWorkspacePayload(o: unknown): o is Record<string, unknown> {
  if (!o || typeof o !== 'object') return false
  const rec = o as Record<string, unknown>
  if (rec.ok === false) return false
  const clusters = rec.clusters
  if (!Array.isArray(clusters) || clusters.length === 0) return false
  const first = clusters[0]
  if (typeof first !== 'object' || first === null) return false
  return 'cluster_id' in first && ('size' in first || 'signals' in first)
}

/** Pinned global-warehouse overlap (from agent tool or console). */
export function isCrossCaseWorkspacePayload(o: unknown): o is Record<string, unknown> {
  if (!o || typeof o !== 'object') return false
  const rec = o as Record<string, unknown>
  return (
    (rec.kind === 'cross_case_matches' || rec.kind === 'global_intelligence_match') &&
    typeof rec.entity_id === 'string' &&
    typeof rec.entity_type === 'string' &&
    Array.isArray(rec.other_cases)
  )
}

type WorkspaceDataContextValue = {
  activeWorkspaceData: ActiveWorkspaceData
  setActiveWorkspaceData: (v: ActiveWorkspaceData) => void
}

const WorkspaceDataContext = createContext<WorkspaceDataContextValue | null>(null)

export function useOptionalWorkspaceData(): WorkspaceDataContextValue | null {
  return useContext(WorkspaceDataContext)
}

export function WorkspaceDataProvider({ children }: { children: ReactNode }) {
  const [activeWorkspaceData, setActiveWorkspaceData] = useState<ActiveWorkspaceData>(null)
  const value = useMemo(
    () => ({ activeWorkspaceData, setActiveWorkspaceData }),
    [activeWorkspaceData],
  )
  return <WorkspaceDataContext.Provider value={value}>{children}</WorkspaceDataContext.Provider>
}

export function useWorkspaceData(): WorkspaceDataContextValue {
  const ctx = useContext(WorkspaceDataContext)
  if (!ctx) {
    throw new Error('useWorkspaceData must be used within WorkspaceDataProvider')
  }
  return ctx
}
