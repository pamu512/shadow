import { useCallback, useEffect, useState } from 'react'
import { fetchEvidenceBoard, getEvidenceWsUrl, patchLead } from '../lib/api'
import type { EvidenceBoardPayload, LeadOut, LeadWorkflowStatus } from '../lib/types'

type Options = {
  pollMs?: number
}

export function useEvidenceBoard(caseId: string | null, { pollMs = 12000 }: Options = {}) {
  const [data, setData] = useState<EvidenceBoardPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [freshLeadIds, setFreshLeadIds] = useState<Set<string>>(() => new Set())

  const pull = useCallback(async () => {
    if (!caseId) return
    setLoading(true)
    try {
      const next = await fetchEvidenceBoard(caseId)
      setData(next)
      setErr(null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => {
    if (!caseId) {
      queueMicrotask(() => {
        setData(null)
        setErr(null)
      })
      return
    }
    let cancelled = false
    const run = async () => {
      if (cancelled) return
      await pull()
    }
    void run()
    const id = window.setInterval(() => void run(), pollMs)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [caseId, pollMs, pull])

  useEffect(() => {
    if (!caseId) return
    let ws: WebSocket | null = null
    let cancelled = false
    void (async () => {
      try {
        const url = await getEvidenceWsUrl(caseId)
        if (cancelled) return
        ws = new WebSocket(url)
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data as string) as { type?: string; lead?: LeadOut }
            if (msg.type !== 'lead_created' || !msg.lead) return
            const lead = msg.lead
            setData((d) => {
              const cur = d ?? { leads: [], audit_logs: [] }
              const rest = cur.leads.filter((x) => x.id !== lead.id)
              return { ...cur, leads: [lead, ...rest] }
            })
            setFreshLeadIds((s) => new Set(s).add(lead.id))
            window.setTimeout(() => {
              setFreshLeadIds((s) => {
                const n = new Set(s)
                n.delete(lead.id)
                return n
              })
            }, 2800)
          } catch {
            /* ignore malformed */
          }
        }
      } catch {
        /* WS optional; polling still runs */
      }
    })()
    return () => {
      cancelled = true
      ws?.close()
    }
  }, [caseId])

  const patchLeadStatus = useCallback(
    async (leadId: string, status: LeadWorkflowStatus) => {
      if (!caseId) return
      await patchLead(caseId, leadId, status)
      await pull()
    },
    [caseId, pull],
  )

  return { data, loading, err, reload: pull, patchLeadStatus, freshLeadIds }
}
