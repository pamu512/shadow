import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { fetchHealth, getApiBase } from '../lib/api'
import type { HealthResponse } from '../lib/types'

const POLL_MS = 15_000

export function useHealthQuery() {
  const q = useQuery({
    queryKey: ['health'],
    queryFn: async (): Promise<{ health: HealthResponse; apiBase: string }> => {
      const [health, apiBase] = await Promise.all([fetchHealth(), getApiBase()])
      return { health, apiBase }
    },
    refetchInterval: POLL_MS,
  })

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === 'visible') void q.refetch()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [q])

  return {
    apiBase: q.data?.apiBase ?? null,
    health: q.data?.health ?? null,
    isLoading: q.isLoading,
    refresh: () => q.refetch(),
  }
}
