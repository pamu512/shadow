import { useEffect, useState } from 'react'
import { getApiBase, fetchHealth } from '../lib/api'
import type { HealthResponse } from '../lib/types'

export function useApiHealth() {
  const [base, setBase] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)

  useEffect(() => {
    let cancel = false
    ;(async () => {
      const b = await getApiBase()
      if (!cancel) setBase(b)
      try {
        const h = await fetchHealth()
        if (!cancel) setHealth(h)
      } catch {
        if (!cancel) setHealth({ ok: false, ollama_reachable: false })
      }
    })()
    return () => {
      cancel = true
    }
  }, [])

  return { apiBase: base, health, refresh: () => fetchHealth().then(setHealth) }
}
