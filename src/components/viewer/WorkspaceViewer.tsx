import ReactDiffViewer from 'react-diff-viewer-continued'
import { useEffect, useRef, useState } from 'react'
import {
  AGENT_INJECT_EVENT,
  analyzeAtoSession,
  analyzeChargebackCase,
  bulkSuspendBotCluster,
  detectBotClusters,
  downloadRepresentmentPackage,
  executeCode,
  fetchAtoProfile,
  downloadFraudRingNetworkExport,
  fetchFraudNetworkRings,
  killAtoSession,
  optimizeThresholds,
  previewCase,
  scaffoldCode,
  simulateRepresentment,
} from '../../lib/api'
import type { CaseOut } from '../../lib/types'
import { WORKSPACE_TAB_EVENT } from '../../lib/workspaceEvents'
import { useEvidenceBoard } from '../../hooks/useEvidenceBoard'
import { isBotClusterWorkspacePayload, isCrossCaseWorkspacePayload, useWorkspaceData } from '../../context/WorkspaceDataContext'
import { GhostButton } from '../ui/ForensicChrome'
import { JsonTreeManifest } from '../ui/JsonTreeManifest'
import { BotClustersWorkspaceTable } from './BotClustersWorkspaceTable'
import { EvidenceBoard } from './EvidenceBoard'
import { RingConnectionMap, type RingGraphLink, type RingGraphNode } from './RingConnectionMap'
import { CrossCaseMatchesPanel } from './CrossCaseMatchesPanel'
import { WorkbenchStrip } from './WorkbenchStrip'
import { HardwareFingerprintGallery } from './HardwareFingerprintGallery'
import { WorkspaceLeadsPanel } from './WorkspaceLeadsPanel'
import type { PinnedForensicPayload } from '../console/ForensicResultTranscriptCard'

type Props = {
  activeCase: CaseOut | null
  review: { original: string; suggested: string; notes: string } | null
  onActivateCase: (c: CaseOut) => void
  /** Drives default workspace tab (e.g. Bot Clusters vs ATO Session). */
  agentPersonaId?: string | null
  workbenchPins?: PinnedForensicPayload[]
  onWorkbenchUnpin?: (id: string) => void
}

type TabId = 'diff' | 'ml' | 'table' | 'evidence' | 'dispute' | 'ato' | 'bots' | 'rings' | 'hardware' | 'leads' | 'crosscase'

const DEFAULT_ATO_SESSION = `{
  "latitude": 51.5074,
  "longitude": -0.1278,
  "timestamp": "2025-06-01T14:30:00",
  "original_email": "jane.doe@example.com",
  "user_agent": "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/120.0",
  "screen_width": 800,
  "screen_height": 600,
  "isp": "Hetzner Online GmbH",
  "is_hosting_or_proxy": true,
  "hardware_id": "fp-never-seen",
  "events": [{"type": "password_change", "at": "2025-06-01T14:25:00"}],
  "high_value_amount": 2000,
  "checkout_duration_seconds": 14
}`

function quickHash(s: string): string {
  let h = 5381
  for (let i = 0; i < s.length; i++) h = (h * 33 + s.charCodeAt(i)) | 0
  return (h >>> 0).toString(16)
}

function safetyBarClass(score: number): string {
  if (score >= 70) return 'from-emerald-600/90 to-emerald-400/80'
  if (score >= 40) return 'from-amber-600/90 to-amber-400/80'
  return 'from-red-700/95 to-rose-400/85'
}

type BotTimelineBin = {
  window_start: string
  total_users: number
  bot_users: number
  human_users: number
  bot_pct: number
  human_pct?: number
}

const diffStyles = {
  variables: {
    dark: {
      diffViewerBackground: '#09090b',
      gutterBackground: '#18181b',
      addedBackground: 'rgba(16,185,129,0.08)',
      removedBackground: 'rgba(244,63,94,0.08)',
      wordAddedBackground: 'rgba(16,185,129,0.2)',
      wordRemovedBackground: 'rgba(244,63,94,0.2)',
      addedColor: '#a7f3d0',
      removedColor: '#fda4af',
      diffViewerColor: '#e4e4e7',
      diffViewerTitleBackground: '#18181b',
      diffViewerTitleColor: '#a1a1aa',
    },
  },
} as const

function initialWorkspaceTab(personaId: string | null | undefined): TabId {
  const p = (personaId ?? 'general').trim() || 'general'
  if (p === 'bot_hunter') return 'bots'
  if (p === 'ato_investigator') return 'ato'
  return 'diff'
}

function insertWorkspaceUtilityTabs(
  base: { id: TabId; label: string }[],
  opts: { showLeads: boolean; showCrossCase: boolean },
): { id: TabId; label: string }[] {
  if (!opts.showLeads && !opts.showCrossCase) return base
  const ev = base[base.length - 1]
  const head = base.slice(0, -1)
  const mid: { id: TabId; label: string }[] = []
  if (opts.showLeads) mid.push({ id: 'leads', label: 'Active leads' })
  if (opts.showCrossCase) mid.push({ id: 'crosscase', label: 'Cross-case' })
  return [...head, ...mid, ev]
}

export function WorkspaceViewer({
  activeCase,
  review,
  onActivateCase,
  agentPersonaId,
  workbenchPins = [],
  onWorkbenchUnpin,
}: Props) {
  const [tab, setTab] = useState<TabId>(() => initialWorkspaceTab(agentPersonaId))
  const [mlJson, setMlJson] = useState<string | null>(null)
  const [table, setTable] = useState<{ columns: string[]; rows: Record<string, unknown>[] } | null>(null)
  const [execOut, setExecOut] = useState<string | null>(null)
  const [scaffoldLang, setScaffoldLang] = useState<'python' | 'r'>('python')
  const [disputeAnalysis, setDisputeAnalysis] = useState<Record<string, unknown> | null>(null)
  const [disputeTxnId, setDisputeTxnId] = useState('')
  const [disputeBusy, setDisputeBusy] = useState(false)
  const [disputeErr, setDisputeErr] = useState<string | null>(null)
  const [issuerMemo, setIssuerMemo] = useState<string | null>(null)
  const [atoUserId, setAtoUserId] = useState('')
  const [atoUserCol, setAtoUserCol] = useState('')
  const [atoSessionJson, setAtoSessionJson] = useState(DEFAULT_ATO_SESSION)
  const [atoBaseline, setAtoBaseline] = useState<Record<string, unknown> | null>(null)
  const [atoCompare, setAtoCompare] = useState<Record<string, unknown> | null>(null)
  const [atoBusy, setAtoBusy] = useState(false)
  const [atoErr, setAtoErr] = useState<string | null>(null)
  const [killReason, setKillReason] = useState('')
  const [atoBreachDraftNote, setAtoBreachDraftNote] = useState<string | null>(null)
  const breachDraftKeyRef = useRef<string | null>(null)
  const [botClusters, setBotClusters] = useState<Record<string, unknown> | null>(null)
  const [botBusy, setBotBusy] = useState(false)
  const [botErr, setBotErr] = useState<string | null>(null)
  const [botSelectedId, setBotSelectedId] = useState<string | null>(null)
  const [ringNet, setRingNet] = useState<Record<string, unknown> | null>(null)
  const [ringBusy, setRingBusy] = useState(false)
  const [ringErr, setRingErr] = useState<string | null>(null)
  const [ringFocus, setRingFocus] = useState<Record<string, unknown> | null>(null)
  const [crossCasePayload, setCrossCasePayload] = useState<Record<string, unknown> | null>(null)

  const { activeWorkspaceData, setActiveWorkspaceData } = useWorkspaceData()
  const evBoard = useEvidenceBoard(activeCase?.id ?? null, { pollMs: 12000 })
  const evLeads = evBoard.data?.leads ?? []
  const showLeadsTab = Boolean(activeCase?.id) && (evBoard.loading || evLeads.length > 0)
  const hasCrossCasePayload = Boolean(crossCasePayload && isCrossCaseWorkspacePayload(crossCasePayload))
  const showCrossCaseTab = hasCrossCasePayload || workbenchPins.length > 0

  const personaTabSyncRef = useRef<string | undefined>(undefined)
  useEffect(() => {
    const pid = (agentPersonaId ?? 'general').trim() || 'general'
    if (personaTabSyncRef.current === undefined) {
      personaTabSyncRef.current = pid
      return
    }
    if (personaTabSyncRef.current === pid) return
    personaTabSyncRef.current = pid
    if (pid === 'bot_hunter') setTab('bots')
    else if (pid === 'ato_investigator') setTab('ato')
    else setTab('diff')
  }, [agentPersonaId])

  useEffect(() => {
    if (!activeWorkspaceData || !isCrossCaseWorkspacePayload(activeWorkspaceData)) return
    setCrossCasePayload(activeWorkspaceData)
    setActiveWorkspaceData(null)
  }, [activeWorkspaceData, setActiveWorkspaceData])

  useEffect(() => {
    const onTab = (e: Event) => {
      const raw = (e as CustomEvent<{ tab?: string }>).detail?.tab
      if (!raw) return
      const allowed: TabId[] = [
        'diff',
        'ml',
        'table',
        'evidence',
        'dispute',
        'ato',
        'bots',
        'rings',
        'hardware',
        'leads',
        'crosscase',
      ]
      if (allowed.includes(raw as TabId)) setTab(raw as TabId)
    }
    window.addEventListener(WORKSPACE_TAB_EVENT, onTab as EventListener)
    return () => window.removeEventListener(WORKSPACE_TAB_EVENT, onTab as EventListener)
  }, [])

  useEffect(() => {
    if (tab === 'leads' && activeCase?.id && !evBoard.loading && evLeads.length === 0) {
      setTab('diff')
    }
  }, [tab, activeCase?.id, evBoard.loading, evLeads.length])

  useEffect(() => {
    if (tab === 'crosscase' && !showCrossCaseTab) {
      setTab('diff')
    }
  }, [tab, showCrossCaseTab])

  useEffect(() => {
    if (!activeWorkspaceData || !isBotClusterWorkspacePayload(activeWorkspaceData)) return
    setBotClusters(activeWorkspaceData)
    setBotErr(null)
    setBotSelectedId(null)
    setTab('bots')
    setActiveWorkspaceData(null)
  }, [activeWorkspaceData, setActiveWorkspaceData])

  useEffect(() => {
    breachDraftKeyRef.current = null
    setAtoBreachDraftNote(null)
  }, [activeCase?.id, atoUserId])

  const prevWorkspaceCaseIdRef = useRef<string | null | undefined>(undefined)

  useEffect(() => {
    if (!activeCase?.id) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDisputeAnalysis(null)
      setIssuerMemo(null)
      setAtoBaseline(null)
      setAtoCompare(null)
      setAtoErr(null)
      setBotClusters(null)
      setBotErr(null)
      setBotSelectedId(null)
      setRingNet(null)
      setRingErr(null)
      setRingFocus(null)
      setCrossCasePayload(null)
    }
  }, [activeCase?.id])

  /** Bot / ring / cross-case panels are per-case — clear stale results when switching between two cases. */
  useEffect(() => {
    const id = activeCase?.id ?? null
    if (prevWorkspaceCaseIdRef.current === undefined) {
      prevWorkspaceCaseIdRef.current = id
      return
    }
    if (prevWorkspaceCaseIdRef.current === id) return
    prevWorkspaceCaseIdRef.current = id
    setBotClusters(null)
    setBotErr(null)
    setBotSelectedId(null)
    setRingNet(null)
    setRingErr(null)
    setRingFocus(null)
    setCrossCasePayload(null)
  }, [activeCase?.id])

  const runChargebackScan = async () => {
    if (!activeCase?.id) return
    setDisputeBusy(true)
    setDisputeErr(null)
    try {
      const r = await analyzeChargebackCase(activeCase.id)
      setDisputeAnalysis(r)
    } catch (e) {
      setDisputeErr(e instanceof Error ? e.message : String(e))
      setDisputeAnalysis(null)
    } finally {
      setDisputeBusy(false)
    }
  }

  const runIssuerSimulation = async () => {
    if (!activeCase?.id) return
    setDisputeBusy(true)
    setDisputeErr(null)
    setIssuerMemo(null)
    try {
      const tid = disputeTxnId.trim() || null
      const r = await simulateRepresentment(activeCase.id, tid)
      if (!r.ok) {
        setDisputeErr(String((r as { error?: string }).error ?? 'Simulation failed'))
        return
      }
      setIssuerMemo(String((r as { issuer_perspective_memo?: string }).issuer_perspective_memo ?? ''))
    } catch (e) {
      setDisputeErr(e instanceof Error ? e.message : String(e))
    } finally {
      setDisputeBusy(false)
    }
  }

  const loadAtoBaseline = async () => {
    if (!activeCase?.id || !atoUserId.trim()) {
      setAtoErr('Enter a user id.')
      return
    }
    setAtoBusy(true)
    setAtoErr(null)
    try {
      const r = await fetchAtoProfile(activeCase.id, atoUserId.trim(), atoUserCol.trim() || null)
      setAtoBaseline(r)
    } catch (e) {
      setAtoErr(e instanceof Error ? e.message : String(e))
      setAtoBaseline(null)
    } finally {
      setAtoBusy(false)
    }
  }

  const runAtoCompare = async () => {
    if (!activeCase?.id) {
      setAtoErr('Select a case.')
      return
    }
    let sess: Record<string, unknown>
    try {
      sess = JSON.parse(atoSessionJson) as Record<string, unknown>
    } catch {
      setAtoErr('Current session JSON is invalid.')
      return
    }
    setAtoBusy(true)
    setAtoErr(null)
    try {
      const r = await analyzeAtoSession(
        activeCase.id,
        atoUserId.trim() || null,
        sess,
        atoUserCol.trim() || null,
      )
      setAtoCompare(r)
      setAtoBreachDraftNote(null)
      if (!r.ok) {
        setAtoErr(String((r as { error?: string }).error ?? 'Analysis failed'))
      } else {
        const rawSafety = r.safety_score
        const riskN = Number(r.ato_risk_score ?? 0)
        const safety =
          rawSafety !== undefined && rawSafety !== null
            ? Number(rawSafety)
            : Math.max(0, Math.min(100, 100 - (Number.isFinite(riskN) ? riskN : 0)))
        const flagsArr = (r.flags as { code?: string }[]) ?? []
        const flagCount = Array.isArray(flagsArr) ? flagsArr.length : 0
        const codes = flagsArr.map((f) => f.code).filter(Boolean).join(', ')
        const notifyTo = (r.notification_recipient_email as string | null | undefined) ?? null

        if (safety < 20 && flagCount > 0 && activeCase.id) {
          const uidKey = atoUserId.trim() || String((r as { user_id?: string }).user_id ?? 'auto')
          const draftKey = `${activeCase.id}:${uidKey}:${quickHash(atoSessionJson)}`
          if (breachDraftKeyRef.current !== draftKey) {
            breachDraftKeyRef.current = draftKey
            const emailLine = notifyTo
              ? `Trusted / pre-change notification address: ${notifyTo}`
              : 'Trusted / pre-change email not present in session JSON — draft the email body anyway and state the address must be pulled from IAM or the user registry.'
            const injectText =
              `/system — ATO triage: Session comparison returned **safety_score ${safety.toFixed(1)}/100** (critical) for user \`${uidKey}\`. ` +
              `Active ATO codes: ${codes || '(see tools)'}. ${emailLine} ` +
              `Draft a breach-notification email to that **original** address only (never a newly attacker-set inbox). ` +
              `Label output **DRAFT — not sent**. One-line risk summary, then Subject + body.`

            window.dispatchEvent(
              new CustomEvent(AGENT_INJECT_EVENT, {
                detail: { text: injectText, persona_id: 'ato_investigator' },
              }),
            )
            setAtoBreachDraftNote('Safety critical — ATO Investigator is drafting a user notification in the agent console.')
          }
        }
      }
    } catch (e) {
      setAtoErr(e instanceof Error ? e.message : String(e))
      setAtoCompare(null)
    } finally {
      setAtoBusy(false)
    }
  }

  const runKillSession = async () => {
    if (!activeCase?.id || !atoUserId.trim()) {
      setAtoErr('Enter a user id.')
      return
    }
    setAtoBusy(true)
    setAtoErr(null)
    try {
      await killAtoSession(activeCase.id, atoUserId.trim(), {
        reason: killReason.trim() || null,
      })
      setKillReason('')
    } catch (e) {
      setAtoErr(e instanceof Error ? e.message : String(e))
    } finally {
      setAtoBusy(false)
    }
  }

  const runBotDetect = async () => {
    if (!activeCase?.id) {
      setBotErr('Select a case.')
      return
    }
    if (!activeCase.dataset_path) {
      setBotErr('Case needs an uploaded CSV (dataset_path).')
      return
    }
    setBotBusy(true)
    setBotErr(null)
    setBotSelectedId(null)
    try {
      const r = await detectBotClusters(activeCase.id)
      setBotClusters(r)
      // Backend uses ok===false only for hard failures (missing file, empty CSV). Degraded / mapped columns use ok true.
      if (r.ok === false) {
        setBotErr(String((r as { error?: string }).error ?? 'Detection failed'))
      }
    } catch (e) {
      setBotErr(e instanceof Error ? e.message : String(e))
      setBotClusters(null)
    } finally {
      setBotBusy(false)
    }
  }

  const runBulkSuspendCluster = async () => {
    if (!activeCase?.id || !botSelectedId || !botClusters || botClusters.ok !== true) {
      setBotErr('Select a cluster row first.')
      return
    }
    const rows = (botClusters.clusters as Record<string, unknown>[]) || []
    const cl = rows.find((c) => String(c.cluster_id) === botSelectedId)
    if (!cl) {
      setBotErr('Cluster not found.')
      return
    }
    const ids = (cl.account_ids as string[]) || []
    if (ids.length === 0) {
      setBotErr('No account ids on this cluster.')
      return
    }
    setBotBusy(true)
    setBotErr(null)
    try {
      await bulkSuspendBotCluster(activeCase.id, {
        account_ids: ids,
        reason: `BOT_CLUSTER:${String(cl.cluster_type)}:${botSelectedId}`,
        cluster_id: botSelectedId,
      })
    } catch (e) {
      setBotErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBotBusy(false)
    }
  }

  const runFraudRingScan = async () => {
    if (!activeCase?.id) {
      setRingErr('Select a case.')
      return
    }
    if (!activeCase.dataset_path) {
      setRingErr('Case needs an uploaded CSV.')
      return
    }
    setRingBusy(true)
    setRingErr(null)
    setRingFocus(null)
    try {
      const r = await fetchFraudNetworkRings(activeCase.id)
      setRingNet(r)
      if (!r.ok) {
        setRingErr(String((r as { error?: string }).error ?? 'Network analysis failed'))
      }
    } catch (e) {
      setRingErr(e instanceof Error ? e.message : String(e))
      setRingNet(null)
    } finally {
      setRingBusy(false)
    }
  }

  const runRingNetworkExport = async (fmt: 'gexf' | 'graphml') => {
    if (!activeCase?.id) {
      setRingErr('Select a case.')
      return
    }
    if (!activeCase.dataset_path) {
      setRingErr('Case needs an uploaded CSV.')
      return
    }
    setRingBusy(true)
    setRingErr(null)
    try {
      const blob = await downloadFraudRingNetworkExport(activeCase.id, fmt)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `fraud_ring_${activeCase.id}.${fmt}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setRingErr(e instanceof Error ? e.message : String(e))
    } finally {
      setRingBusy(false)
    }
  }

  const downloadPackage = async () => {
    if (!activeCase?.id || !disputeTxnId.trim()) {
      setDisputeErr('Enter a transaction id to export.')
      return
    }
    setDisputeBusy(true)
    setDisputeErr(null)
    try {
      const blob = await downloadRepresentmentPackage(activeCase.id, disputeTxnId.trim())
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `representment_${disputeTxnId.trim().replace(/[^a-zA-Z0-9._-]+/g, '_')}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setDisputeErr(e instanceof Error ? e.message : String(e))
    } finally {
      setDisputeBusy(false)
    }
  }

  useEffect(() => {
    if (!activeCase?.dataset_path) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear preview when no dataset
      setTable(null)
      return
    }
    void previewCase(activeCase.id, 30)
      .then(setTable)
      .catch(() => setTable(null))
  }, [activeCase?.id, activeCase?.dataset_path])

  const runMl = async () => {
    try {
      const r = await optimizeThresholds('isolation_forest', activeCase?.id)
      setMlJson(JSON.stringify(r, null, 2))
      setTab('ml')
    } catch (e) {
      setMlJson(String(e))
      setTab('ml')
    }
  }

  const runScaffold = async () => {
    try {
      const r = await scaffoldCode(scaffoldLang, 'Feature engineering for fraud signals', activeCase?.id)
      setExecOut(`${r.explanation}\n\n${r.code}`)
    } catch (e) {
      setExecOut(String(e))
    }
  }

  const runSandboxSmoke = async () => {
    const code =
      scaffoldLang === 'python'
        ? 'import polars as pl\nprint("ok", pl.DataFrame({"a": [1]}).height)'
        : 'print("hello R")\n'
    try {
      const r = await executeCode(scaffoldLang, code, activeCase?.id)
      setExecOut(`exit ${r.exit_code}\n${r.stdout}\n${r.stderr}\nviolations: ${(r.violations || []).join('; ')}`)
    } catch (e) {
      setExecOut(String(e))
    }
  }

  const personaKey = (agentPersonaId ?? 'general').trim() || 'general'
  const personaTabs: { id: TabId; label: string }[] =
    personaKey === 'bot_hunter'
      ? [
          { id: 'bots', label: 'Cluster map' },
          { id: 'hardware', label: 'Hardware gallery' },
          { id: 'diff', label: 'Diff' },
          { id: 'ml', label: 'ML manifest' },
          { id: 'table', label: 'Dataset' },
          { id: 'dispute', label: 'Dispute Desk' },
          { id: 'ato', label: 'ATO Session' },
          { id: 'rings', label: 'Connection Map' },
          { id: 'evidence', label: 'Evidence Board' },
        ]
      : personaKey === 'ato_investigator'
        ? [
            { id: 'ato', label: 'Impossible travel' },
            { id: 'diff', label: 'Diff' },
            { id: 'ml', label: 'ML manifest' },
            { id: 'table', label: 'Dataset' },
            { id: 'dispute', label: 'Dispute Desk' },
            { id: 'bots', label: 'Bot Clusters' },
            { id: 'rings', label: 'Connection Map' },
            { id: 'evidence', label: 'Evidence Board' },
          ]
        : [
            { id: 'diff', label: 'Diff' },
            { id: 'ml', label: 'ML manifest' },
            { id: 'table', label: 'Dataset' },
            { id: 'dispute', label: 'Dispute Desk' },
            { id: 'ato', label: 'ATO Session' },
            { id: 'bots', label: 'Bot Clusters' },
            { id: 'rings', label: 'Connection Map' },
            { id: 'evidence', label: 'Evidence Board' },
          ]
  const tabs = insertWorkspaceUtilityTabs(personaTabs, {
    showLeads: showLeadsTab,
    showCrossCase: showCrossCaseTab,
  })

  const atoSafetyNum =
    atoCompare?.ok === true
      ? Number(atoCompare.safety_score ?? Math.max(0, 100 - Number(atoCompare.ato_risk_score ?? 0)))
      : null

  const botAlertThreshold =
    typeof botClusters?.bot_window_alert_threshold_pct === 'number'
      ? Number(botClusters.bot_window_alert_threshold_pct)
      : 40
  const botTimeline5m = (botClusters?.timeline_5m as BotTimelineBin[] | undefined) ?? []
  const botHighAlert =
    botClusters?.ok === true &&
    (Boolean(botClusters.high_bot_window_alert) ||
      botTimeline5m.some((w) => Number(w.bot_pct) > botAlertThreshold))

  return (
    <div className="flex h-full min-w-0 flex-col bg-[#0d0d0d]/98 text-xs text-zinc-200 backdrop-blur-sm">
      <WorkbenchStrip
        items={workbenchPins}
        onUnpin={(id) => onWorkbenchUnpin?.(id)}
        caseName={activeCase?.name ?? null}
      />
      <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-end gap-1 border-b border-zinc-800 px-2 pt-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`relative rounded-t-lg px-3 py-2 text-[11px] font-medium tracking-wide transition-colors ${
              tab === t.id
                ? 'text-zinc-100 after:absolute after:bottom-0 after:left-2 after:right-2 after:h-0.5 after:rounded-full after:bg-fuchsia-500 after:shadow-[0_0_10px_rgba(192,38,211,0.5)]'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {t.label}
          </button>
        ))}
        {tab !== 'evidence' &&
        tab !== 'dispute' &&
        tab !== 'ato' &&
        tab !== 'bots' &&
        tab !== 'rings' &&
        tab !== 'hardware' &&
        tab !== 'leads' &&
        tab !== 'crosscase' ? (
          <button
            type="button"
            onClick={() => void runMl()}
            className="mb-1 ml-auto shrink-0 rounded-lg border border-fuchsia-500/50 bg-fuchsia-500/10 px-3 py-1.5 text-[11px] font-semibold tracking-wide text-fuchsia-100 shadow-[0_0_16px_rgba(168,85,247,0.35)] transition-all hover:border-fuchsia-400/70 hover:shadow-[0_0_22px_rgba(192,38,211,0.45)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-fuchsia-500/50"
          >
            Run optimizer
          </button>
        ) : tab === 'evidence' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Evidence hub</span>
        ) : tab === 'dispute' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Representment</span>
        ) : tab === 'ato' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Session compare</span>
        ) : tab === 'bots' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Cluster map</span>
        ) : tab === 'rings' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Graph evidence</span>
        ) : tab === 'hardware' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Canvas × IP</span>
        ) : tab === 'leads' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Evidence stream</span>
        ) : tab === 'crosscase' ? (
          <span className="mb-1 ml-auto shrink-0 font-mono text-[10px] text-zinc-600">Warehouse</span>
        ) : null}
      </div>

      {tab === 'leads' && (
        <WorkspaceLeadsPanel
          caseId={activeCase?.id ?? null}
          leads={evLeads}
          loading={evBoard.loading}
          err={evBoard.err}
          freshLeadIds={evBoard.freshLeadIds}
        />
      )}

      {tab === 'crosscase' && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {hasCrossCasePayload ? (
            <CrossCaseMatchesPanel
              payload={crossCasePayload}
              activeCaseId={activeCase?.id ?? null}
              onActivateCase={onActivateCase}
            />
          ) : (
            <div className="p-4 text-[11px] leading-relaxed text-zinc-500">
              Cross-case rows appear after a successful{' '}
              <span className="font-mono text-zinc-400">search_historical_overlap_tool</span> push to the workspace, or
              use entity chips in the transcript → Global Warehouse. Pinned workbench items stay above for reference.
            </div>
          )}
        </div>
      )}

      {tab === 'hardware' && (
        <div className="min-h-0 flex-1 overflow-hidden">
          <HardwareFingerprintGallery botClusters={botClusters} />
        </div>
      )}

      {tab === 'diff' && (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          {review ? (
            <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/50">
              <ReactDiffViewer
                oldValue={review.original}
                newValue={review.suggested}
                splitView
                useDarkTheme
                leftTitle="Before"
                rightTitle="After"
                styles={diffStyles}
              />
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-950/30 p-8 text-center font-mono text-[11px] text-zinc-600">
              Awaiting artifact ingest — no diff in queue.
            </div>
          )}
          {review?.notes && (
            <p className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 font-mono text-[11px] text-amber-300/90">{review.notes}</p>
          )}
          <div className="mt-4 space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="rounded-lg border border-zinc-800 bg-zinc-900/90 px-2 py-1.5 font-mono text-[11px] text-zinc-300 focus:border-zinc-700 focus:outline-none"
                value={scaffoldLang}
                onChange={(e) => setScaffoldLang(e.target.value as 'python' | 'r')}
              >
                <option value="python">Python</option>
                <option value="r">R</option>
              </select>
              <GhostButton onClick={() => void runScaffold()}>Scaffold</GhostButton>
              <GhostButton onClick={() => void runSandboxSmoke()}>Sandbox</GhostButton>
            </div>
            {execOut && (
              <pre className="max-h-48 overflow-auto rounded-lg border border-zinc-800 bg-[#09090b] p-2 font-mono text-[11px] text-emerald-200/80">{execOut}</pre>
            )}
          </div>
        </div>
      )}

      {tab === 'ml' && (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          {mlJson ? (
            <JsonTreeManifest jsonText={mlJson} />
          ) : (
            <div className="rounded-lg border border-dashed border-zinc-800 p-8 text-center font-mono text-[11px] text-zinc-600">
              Execute “Run optimizer” to materialize manifest tree.
            </div>
          )}
        </div>
      )}

      {tab === 'dispute' && (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <div className="mb-3 rounded-lg border border-rose-500/20 bg-rose-950/20 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-rose-300/90">Dispute Desk</div>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
              Chargeback Specialist signals: IP/device reuse, post-dispute activity, dispute velocity, billing vs
              shipping, AVS/CVV. Run a scan, simulate how an <span className="text-zinc-400">issuing bank</span> might
              rule on representment, then export a ZIP for an order.
            </p>
          </div>
          {!activeCase?.dataset_path ? (
            <div className="rounded-lg border border-dashed border-zinc-800 p-8 text-center font-mono text-[11px] text-zinc-600">
              Select a case with an uploaded dataset.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <GhostButton disabled={disputeBusy} onClick={() => void runChargebackScan()}>
                  {disputeBusy ? 'Running…' : 'Run chargeback scan'}
                </GhostButton>
                <button
                  type="button"
                  disabled={disputeBusy}
                  className="rounded-lg border border-cyan-500/40 bg-cyan-950/40 px-3 py-1.5 text-[11px] font-semibold tracking-wide text-cyan-200/95 shadow-[0_0_12px_rgba(6,182,212,0.2)] hover:border-cyan-400/55 disabled:opacity-40"
                  onClick={() => void runIssuerSimulation()}
                >
                  {disputeBusy ? '…' : 'Simulate representment (issuer)'}
                </button>
              </div>
              <p className="text-[10px] leading-snug text-zinc-600">
                Issuer simulation uses Ollama: optional transaction id narrows the manifest; leave blank for cohort-only
                review. In the Agent Console, select <span className="text-zinc-500">Chargeback Specialist</span> and the
                Shadow agent can call the same tool.
              </p>
              {disputeErr ? (
                <div className="rounded border border-red-500/30 bg-red-950/30 px-3 py-2 font-mono text-[11px] text-red-300/90">
                  {disputeErr}
                </div>
              ) : null}
              {disputeAnalysis?.ok === false ? (
                <div className="rounded border border-amber-500/25 bg-amber-950/20 px-3 py-2 font-mono text-[11px] text-amber-200/90">
                  {String((disputeAnalysis as { error?: string }).error ?? 'Analysis failed')}
                </div>
              ) : null}
              {issuerMemo ? (
                <div className="rounded-lg border border-cyan-500/25 bg-cyan-950/15 p-3">
                  <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-cyan-400/90">
                    Issuing bank simulation
                  </div>
                  <div className="max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-zinc-300">
                    {issuerMemo}
                  </div>
                </div>
              ) : null}
              {disputeAnalysis && disputeAnalysis.ok !== false ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 shadow-inner">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Chargeback risk score</div>
                    <div className="mt-1 font-mono text-2xl font-bold tabular-nums text-amber-200/95">
                      {Number(disputeAnalysis.chargeback_risk_score ?? 0).toFixed(1)}
                      <span className="ml-1 text-sm font-normal text-zinc-500">/ 100</span>
                    </div>
                    <p className="mt-2 text-[10px] leading-snug text-zinc-600">
                      Higher = more merchant-favorable artifacts detected in-file (not legal advice).
                    </p>
                  </div>
                  <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 shadow-inner">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Est. win probability</div>
                    <div className="mt-1 font-mono text-2xl font-bold tabular-nums text-emerald-300/95">
                      {Number(disputeAnalysis.win_probability_percent ?? 0).toFixed(1)}%
                    </div>
                    <p className="mt-2 text-[10px] leading-snug text-zinc-600">Heuristic from evidence score + signal density.</p>
                  </div>
                </div>
              ) : null}
              {Array.isArray(disputeAnalysis?.executive_summary) && disputeAnalysis.executive_summary.length > 0 ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
                  <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Summary</div>
                  <ul className="list-inside list-disc space-y-1 text-[11px] text-zinc-400">
                    {(disputeAnalysis.executive_summary as string[]).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
                <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                  Representment package
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <label className="flex min-w-[200px] flex-1 flex-col gap-1">
                    <span className="text-[10px] uppercase tracking-wide text-zinc-600">Transaction id</span>
                    <input
                      className="rounded-lg border border-zinc-700 bg-zinc-900/90 px-2 py-2 font-mono text-[11px] text-zinc-200 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none"
                      placeholder="e.g. order_102 or txn id from dataset"
                      value={disputeTxnId}
                      onChange={(e) => setDisputeTxnId(e.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={disputeBusy}
                    className="shrink-0 rounded-lg border border-violet-500/45 bg-violet-500/15 px-4 py-2 text-[11px] font-semibold tracking-wide text-violet-100 shadow-[0_0_14px_rgba(139,92,246,0.25)] hover:border-violet-400/60 disabled:opacity-40"
                    onClick={() => void downloadPackage()}
                  >
                    Download ZIP
                  </button>
                </div>
                <p className="mt-2 text-[10px] text-zinc-600">
                  Exports representment_manifest.json + REPRESENTMENT_SUMMARY.txt (PDF can be generated from the JSON in
                  your doc workflow).
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'ato' && (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          {personaKey === 'ato_investigator' ? (
            <div className="mb-2 rounded-lg border border-rose-500/30 bg-rose-950/20 px-3 py-2">
              <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-rose-300/95">ATO lens · geographic impossible travel</div>
              <p className="mt-1 text-[10px] leading-snug text-zinc-500">
                Baseline vs session deltas below highlight velocity violations and geo jumps—use Compare session after loading baseline.
              </p>
            </div>
          ) : null}
          <div className="mb-3 rounded-lg border border-indigo-500/25 bg-indigo-950/20 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-300/90">ATO session comparison</div>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
              DuckDB baseline vs live session JSON. Flags <span className="text-red-300/90">impossible travel</span>,{' '}
              <span className="text-red-300/90">environment drift</span>, hosting ISP, sensitive change chains, and speed-run
              navigation. Requires an ingested dataset (DuckDB).
            </p>
          </div>
          {!activeCase?.duckdb_path && !activeCase?.dataset_path ? (
            <div className="rounded-lg border border-dashed border-zinc-800 p-8 text-center font-mono text-[11px] text-zinc-600">
              Select a case with an uploaded dataset.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-end gap-2">
                <label className="flex min-w-[120px] flex-col gap-1">
                  <span className="text-[10px] uppercase tracking-wide text-zinc-600">User id</span>
                  <input
                    className="rounded-lg border border-zinc-700 bg-zinc-900/90 px-2 py-2 font-mono text-[11px] text-zinc-200"
                    value={atoUserId}
                    onChange={(e) => setAtoUserId(e.target.value)}
                    placeholder="u_12345"
                  />
                </label>
                <label className="flex min-w-[140px] flex-1 flex-col gap-1">
                  <span className="text-[10px] uppercase tracking-wide text-zinc-600">User column (optional)</span>
                  <input
                    className="rounded-lg border border-zinc-700 bg-zinc-900/90 px-2 py-2 font-mono text-[11px] text-zinc-200"
                    value={atoUserCol}
                    onChange={(e) => setAtoUserCol(e.target.value)}
                    placeholder="auto-detect if empty"
                  />
                </label>
                <GhostButton disabled={atoBusy} onClick={() => void loadAtoBaseline()}>
                  Load baseline
                </GhostButton>
                <button
                  type="button"
                  disabled={atoBusy}
                  className="rounded-lg border border-amber-500/45 bg-amber-950/30 px-3 py-2 text-[11px] font-semibold text-amber-200/95 disabled:opacity-40"
                  onClick={() => void runAtoCompare()}
                >
                  Compare session
                </button>
              </div>
              {atoErr ? (
                <div className="rounded border border-red-500/30 bg-red-950/25 px-3 py-2 font-mono text-[11px] text-red-300/90">
                  {atoErr}
                </div>
              ) : null}
              <div className="grid min-h-[280px] gap-3 lg:grid-cols-2">
                <div className="flex min-h-0 flex-col rounded-lg border border-emerald-500/20 bg-zinc-950/50 p-3">
                  <div className="mb-2 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-emerald-400/90">
                    Historical baseline (trusted profile)
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto font-mono text-[10px] leading-relaxed text-zinc-400">
                    {!atoBaseline?.ok ? (
                      <span className="text-zinc-600">Run “Load baseline” for Behavioral DNA.</span>
                    ) : (
                      <pre className="whitespace-pre-wrap">{JSON.stringify(atoBaseline.behavioral_dna ?? {}, null, 2)}</pre>
                    )}
                  </div>
                </div>
                <div className="flex min-h-0 flex-col rounded-lg border border-red-500/25 bg-red-950/10 p-3">
                  <div className="mb-2 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-red-400/90">
                    Current suspicious session
                  </div>
                  <textarea
                    className="mb-2 min-h-[140px] w-full flex-1 resize-y rounded-lg border border-red-500/20 bg-[#0a0a0c] p-2 font-mono text-[10px] text-red-100/90 placeholder:text-zinc-600 focus:border-red-400/40 focus:outline-none"
                    value={atoSessionJson}
                    onChange={(e) => setAtoSessionJson(e.target.value)}
                    spellCheck={false}
                  />
                  {atoCompare?.ok ? (
                    <div className="space-y-2">
                      {atoBreachDraftNote ? (
                        <div className="rounded border border-amber-500/40 bg-amber-950/35 px-2 py-2 text-[10px] font-medium text-amber-200/95">
                          {atoBreachDraftNote}
                        </div>
                      ) : null}
                      <div className="rounded-lg border border-zinc-800/90 bg-zinc-900/50 px-3 py-2.5">
                        <div className="mb-1.5 flex items-baseline justify-between gap-2">
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                            Safety score
                          </span>
                          <span
                            className={`font-mono text-lg font-bold tabular-nums ${
                              atoSafetyNum != null && atoSafetyNum < 40
                                ? 'text-red-300/95'
                                : atoSafetyNum != null && atoSafetyNum < 70
                                  ? 'text-amber-200/95'
                                  : 'text-emerald-300/95'
                            }`}
                          >
                            {atoSafetyNum != null ? atoSafetyNum.toFixed(1) : '—'}
                            <span className="text-[11px] font-normal text-zinc-500">/100</span>
                          </span>
                        </div>
                        <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-800">
                          <div
                            className={`h-full rounded-full bg-gradient-to-r ${safetyBarClass(
                              atoSafetyNum ?? 0,
                            )} transition-[width] duration-500`}
                            style={{
                              width: `${atoSafetyNum ?? 0}%`,
                            }}
                          />
                        </div>
                        <div className="mt-2 font-mono text-[10px] text-zinc-500">
                          ATO risk pressure{' '}
                          <span className="font-semibold text-red-300/90">
                            {Number(atoCompare.ato_risk_score ?? 0).toFixed(1)}
                          </span>
                          <span className="text-zinc-600"> / 100 · higher = more indicators</span>
                          {(atoCompare.notification_recipient_email as string | undefined) ? (
                            <span className="mt-1 block text-emerald-400/85">
                              Notify (trusted): {String(atoCompare.notification_recipient_email)}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <ul className="space-y-1.5">
                        {((atoCompare.flags as { code: string; severity: string; detail: string }[]) || []).map((f) => (
                          <li
                            key={`${f.code}-${f.detail.slice(0, 40)}`}
                            className="rounded border border-red-500/30 bg-red-950/40 px-2 py-1.5 text-[10px] text-red-200/90"
                          >
                            <span className="font-semibold uppercase tracking-wide text-red-300/95">{f.code}</span> ·{' '}
                            {f.detail}
                          </li>
                        ))}
                      </ul>
                      <div className="text-[10px] font-semibold  text-zinc-500">Field discrepancies</div>
                      <ul className="space-y-1">
                        {(
                          (atoCompare.discrepancies as {
                            field: string
                            severity: string
                            baseline_value?: string
                            current_value?: string
                          }[]) || []
                        ).map((d) => (
                          <li
                            key={`${d.field}-${String(d.current_value).slice(0, 20)}`}
                            className={`rounded border px-2 py-1 text-[10px] ${
                              d.severity === 'critical' || d.severity === 'high'
                                ? 'border-red-500/50 bg-red-950/50 text-red-200'
                                : 'border-zinc-700 bg-zinc-900/40 text-zinc-400'
                            }`}
                          >
                            <span className="font-semibold text-zinc-300">{d.field}</span>: baseline{' '}
                            <span className="text-emerald-200/80">{String(d.baseline_value ?? '—')}</span> → current{' '}
                            <span className="text-red-300/90">{String(d.current_value ?? '—')}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap items-end gap-2 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
                <label className="flex min-w-[200px] flex-1 flex-col gap-1">
                  <span className="text-[10px] uppercase tracking-wide text-zinc-600">Kill session reason (audit)</span>
                  <input
                    className="rounded-lg border border-zinc-700 bg-zinc-900/90 px-2 py-2 font-mono text-[11px] text-zinc-200"
                    value={killReason}
                    onChange={(e) => setKillReason(e.target.value)}
                    placeholder="ATO triage — suspected hijack"
                  />
                </label>
                <button
                  type="button"
                  disabled={atoBusy}
                  className="rounded-lg border border-rose-600/50 bg-rose-950/40 px-4 py-2 text-[11px] font-bold uppercase tracking-wide text-rose-200/95 hover:bg-rose-900/50 disabled:opacity-40"
                  onClick={() => void runKillSession()}
                >
                  Kill session (log)
                </button>
              </div>
              <p className="text-[10px] text-zinc-600">
                Kill session records an audit event; connect your IdP/revocation service to revoke live tokens.
              </p>
            </div>
          )}
        </div>
      )}

      {tab === 'bots' && (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <div className="mb-3 rounded-lg border border-cyan-500/25 bg-cyan-950/15 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-300/90">Bot cluster map</div>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
              Polars detection: signup <span className="text-cyan-200/90">time bursts</span>, shared /24 + UA or canvas
              overlap, disposable domains, Gmail dot variants, high-entropy locals. Select a row to drill into account ids;
              bulk suspend writes an audit entry (wire your user store to enforce).
            </p>
          </div>
          {!activeCase?.dataset_path ? (
            <div className="rounded-lg border border-dashed border-zinc-800 p-8 text-center font-mono text-[11px] text-zinc-600">
              Upload a case CSV to run bot clustering.
            </div>
          ) : (
            <div
              className={
                botHighAlert
                  ? 'space-y-3 rounded-xl border-2 border-red-500/80 p-3 shadow-[0_0_36px_rgba(239,68,68,0.45),0_0_72px_rgba(220,38,38,0.18),inset_0_0_24px_rgba(127,29,29,0.12)]'
                  : 'space-y-3'
              }
            >
              {botClusters && botClusters.ok === true && botHighAlert ? (
                <div className="flex items-center gap-2 rounded-lg border border-red-500/55 bg-red-950/45 px-3 py-2.5 text-[10px] font-bold uppercase tracking-[0.12em] text-red-100 shadow-[0_0_20px_rgba(239,68,68,0.35)]">
                  <span
                    className="inline-flex h-2.5 w-2.5 shrink-0 rounded-full bg-red-500 shadow-[0_0_10px_#f87171,0_0_18px_rgba(239,68,68,0.8)]"
                    aria-hidden
                  />
                  High alert — bot registrations &gt; {botAlertThreshold}% in one or more 5-minute windows (peak{' '}
                  {Number(botClusters.max_bot_pct_5m_window ?? 0).toFixed(1)}%)
                </div>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={botBusy}
                  className="rounded-lg border border-cyan-500/45 bg-cyan-950/35 px-4 py-2 text-[11px] font-bold uppercase tracking-wide text-cyan-100/95 disabled:opacity-40"
                  onClick={() => void runBotDetect()}
                >
                  Run bot detection
                </button>
              </div>
              {botErr ? (
                <div className="rounded border border-red-500/30 bg-red-950/25 px-3 py-2 font-mono text-[11px] text-red-300/90">
                  {botErr}
                </div>
              ) : null}
              {botClusters && botClusters.ok === true && botClusters.analysis_degraded === true ? (
                <div className="rounded border border-cyan-500/35 bg-cyan-950/20 px-3 py-2 font-mono text-[11px] leading-relaxed text-cyan-100/90">
                  Partial detection (time/user columns incomplete for full bursts). Canvas × IP forensics below are
                  still valid — re-run after fixing CSV headers if you need full timelines.
                  {typeof botClusters.analysis_degraded_reason === 'string' ? (
                    <span className="mt-1 block text-[10px] text-cyan-200/70">
                      ({botClusters.analysis_degraded_reason})
                    </span>
                  ) : null}
                </div>
              ) : null}
              {botClusters && botClusters.ok === true ? (
                <>
                  <div className="rounded-xl border border-zinc-800 bg-gradient-to-br from-rose-950/40 via-zinc-950/80 to-zinc-950 p-4 shadow-[0_0_32px_rgba(244,63,94,0.06)]">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Bot density</div>
                    <div className="mt-1 flex items-baseline gap-2">
                      <span className="font-mono text-3xl font-bold tabular-nums text-rose-300/95">
                        {Number(botClusters.bot_density_pct ?? 0).toFixed(2)}
                      </span>
                      <span className="text-sm text-zinc-500">% of accounts touching ≥1 cluster</span>
                    </div>
                    <div className="mt-2 font-mono text-[10px] text-zinc-500">
                      rows {String(botClusters.row_count ?? '—')} · unique users {String(botClusters.unique_users ?? '—')} ·
                      clusters {String((botClusters.clusters as unknown[])?.length ?? 0)}
                    </div>
                  </div>
                  <div
                    className={`rounded-xl border bg-gradient-to-br from-zinc-900/90 via-zinc-950/80 to-zinc-950 p-4 ${
                      botHighAlert
                        ? 'border-red-500/55 shadow-[0_0_28px_rgba(239,68,68,0.3)]'
                        : 'border-zinc-800'
                    }`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                          Bot-to-human ratio
                        </div>
                        <p className="mt-0.5 max-w-xl text-[10px] leading-snug text-zinc-600">
                          Each bar is a 5-minute signup window: rose = accounts flagged as automated (cluster membership),
                          emerald = remainder. Windows above {botAlertThreshold}% bot are highlighted.
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-4 font-mono text-[9px] text-zinc-500">
                        <span>
                          <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-rose-500/95 align-middle" /> bot
                        </span>
                        <span>
                          <span className="mr-1 inline-block h-2 w-2 rounded-sm bg-emerald-600/90 align-middle" /> human
                        </span>
                      </div>
                    </div>
                    <div className="mt-3 max-h-[240px] space-y-2.5 overflow-auto pr-1">
                      {botTimeline5m.length === 0 ? (
                        <p className="text-[10px] text-zinc-600">No 5-minute windows (timestamps missing or sparse).</p>
                      ) : (
                        botTimeline5m.map((w) => {
                          const pct = Math.min(100, Math.max(0, Number(w.bot_pct)))
                          const hot = pct > botAlertThreshold
                          return (
                            <div
                              key={w.window_start}
                              className={
                                hot
                                  ? 'rounded-lg border border-red-500/60 bg-red-950/30 p-2 shadow-[0_0_14px_rgba(239,68,68,0.22)]'
                                  : 'rounded-lg border border-zinc-800/90 bg-zinc-950/50 p-2'
                              }
                            >
                              <div className="mb-1 flex flex-wrap items-center justify-between gap-2 font-mono text-[9px] text-zinc-400">
                                <span className="min-w-0 truncate" title={w.window_start}>
                                  {w.window_start.replace('T', ' ').slice(0, 19)}
                                </span>
                                <span className={hot ? 'font-semibold text-red-300' : 'text-zinc-500'}>
                                  {pct.toFixed(1)}% bot · {w.bot_users} bot / {w.total_users} accts
                                </span>
                              </div>
                              <div className="flex h-4 w-full overflow-hidden rounded-md bg-zinc-800">
                                <div
                                  className="h-full bg-gradient-to-b from-rose-400/95 to-rose-600/90"
                                  style={{ width: `${pct}%` }}
                                />
                                <div
                                  className="h-full bg-gradient-to-b from-emerald-500/90 to-emerald-700/85"
                                  style={{ width: `${100 - pct}%` }}
                                />
                              </div>
                            </div>
                          )
                        })
                      )}
                    </div>
                  </div>
                  <div className="flex min-h-[320px] flex-col gap-3">
                    <BotClustersWorkspaceTable
                      clusters={(botClusters.clusters as Record<string, unknown>[]) || []}
                      selectedClusterId={botSelectedId}
                      onSelectCluster={(id) => setBotSelectedId(id)}
                    />
                    <div className="flex min-h-0 flex-col rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Drill-down</div>
                      {botSelectedId && botClusters.ok === true ? (
                        (() => {
                          const rows = (botClusters.clusters as Record<string, unknown>[]) || []
                          const cl = rows.find((x) => String(x.cluster_id) === botSelectedId)
                          if (!cl) {
                            return <p className="mt-2 text-[11px] text-zinc-600">Select a cluster.</p>
                          }
                          const traits = (cl.common_traits as string[]) || []
                          const ids = (cl.account_ids as string[]) || []
                          const trunc = Number(cl.account_ids_truncated ?? 0)
                          return (
                            <div className="mt-2 flex min-h-0 flex-1 flex-col gap-2">
                              <ul className="list-inside list-disc text-[10px] text-zinc-400">
                                {traits.map((t, i) => (
                                  <li key={i} className="leading-relaxed">
                                    {t}
                                  </li>
                                ))}
                              </ul>
                              {trunc > 0 ? (
                                <div className="rounded border border-amber-500/30 bg-amber-950/20 px-2 py-1.5 text-[10px] text-amber-200/90">
                                  {trunc} additional accounts not loaded in this payload — re-run from API or use the agent tool
                                  for the full id list.
                                </div>
                              ) : null}
                              <div className="min-h-0 flex-1 overflow-auto rounded border border-zinc-800 bg-[#0c0c0e] p-2">
                                <div className="mb-1 text-[9px] font-semibold uppercase text-zinc-600">Account ids</div>
                                <ul className="space-y-0.5 font-mono text-[10px] text-emerald-200/85">
                                  {ids.map((aid) => (
                                    <li key={aid}>{aid}</li>
                                  ))}
                                </ul>
                              </div>
                              <button
                                type="button"
                                disabled={botBusy || ids.length === 0}
                                className="w-full rounded-lg border border-rose-600/55 bg-rose-950/50 py-3 text-[12px] font-bold uppercase tracking-wide text-rose-100/95 hover:bg-rose-900/45 disabled:opacity-40"
                                onClick={() => void runBulkSuspendCluster()}
                              >
                                Bulk suspend cluster (audit)
                              </button>
                            </div>
                          )
                        })()
                      ) : (
                        <p className="mt-2 text-[11px] text-zinc-600">Select a cluster row to view members.</p>
                      )}
                    </div>
                  </div>
                </>
              ) : botClusters && botClusters.ok === false ? (
                <div className="rounded border border-amber-500/30 bg-amber-950/20 px-3 py-2 font-mono text-[11px] text-amber-200/90">
                  Detection could not run: {String((botClusters as { error?: string }).error ?? 'unknown')}. Check that
                  the case CSV path exists and the sidecar is running the latest build.
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}

      {tab === 'rings' && (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <div className="mb-3 rounded-lg border border-violet-500/25 bg-violet-950/15 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-300/90">
              Connection map (collusion graph)
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
              Polars + NetworkX: shared <span className="text-violet-200/90">device / address / phone</span>,{' '}
              <span className="text-zinc-300">payment cycles</span>, Louvain communities, employee↔account hotspots.
              Click a node to inject its metadata into the Fraud Ring Detective channel.
            </p>
          </div>
          {!activeCase?.dataset_path ? (
            <div className="rounded-lg border border-dashed border-zinc-800 p-8 text-center font-mono text-[11px] text-zinc-600">
              Upload a case CSV to build the relationship graph.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={ringBusy}
                  className="rounded-lg border border-violet-500/45 bg-violet-950/35 px-4 py-2 text-[11px] font-bold uppercase tracking-wide text-violet-100/95 disabled:opacity-40"
                  onClick={() => void runFraudRingScan()}
                >
                  Run ring detection
                </button>
                <button
                  type="button"
                  disabled={ringBusy}
                  className="rounded-lg border border-zinc-600/70 bg-zinc-900/80 px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-200 hover:border-zinc-500 disabled:opacity-40"
                  onClick={() => void runRingNetworkExport('gexf')}
                >
                  Export GEXF (Gephi)
                </button>
                <button
                  type="button"
                  disabled={ringBusy}
                  className="rounded-lg border border-zinc-600/70 bg-zinc-900/80 px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-200 hover:border-zinc-500 disabled:opacity-40"
                  onClick={() => void runRingNetworkExport('graphml')}
                >
                  Export GraphML
                </button>
              </div>
              <p className="text-[10px] text-zinc-600">
                Network export is the <span className="text-zinc-400">full</span> collusion graph with node roles
                and communities (not the UI-trimmed preview). Open in Gephi, Cytoscape, or yEd.
              </p>
              {ringErr ? (
                <div className="rounded border border-red-500/30 bg-red-950/25 px-3 py-2 font-mono text-[11px] text-red-300/90">
                  {ringErr}
                </div>
              ) : null}
              {ringNet && ringNet.ok === true ? (
                <>
                  <div className="grid gap-3 lg:grid-cols-[1fr_280px]">
                    <RingConnectionMap
                      graphData={
                        ringNet.graph_data as {
                          nodes: RingGraphNode[]
                          links: RingGraphLink[]
                        }
                      }
                      onNodeFocus={(n) => setRingFocus(n as unknown as Record<string, unknown>)}
                    />
                    <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/50 p-3 font-mono text-[10px] text-zinc-400">
                      <div className="font-semibold uppercase tracking-wider text-zinc-500">Graph summary</div>
                      <div>Nodes: {String((ringNet.graph_summary as { nodes?: number })?.nodes ?? '—')}</div>
                      <div>Edges: {String((ringNet.graph_summary as { edges?: number })?.edges ?? '—')}</div>
                      <div>Communities: {String(ringNet.community_count ?? '—')}</div>
                      <div>Cycles: {String(ringNet.cycles_found ?? 0)}</div>
                      {(ringNet.visualization_note as string | undefined) ? (
                        <div className="text-amber-200/85">{String(ringNet.visualization_note)}</div>
                      ) : null}
                      {ringFocus ? (
                        <div className="mt-2 border-t border-zinc-800 pt-2">
                          <div className="mb-1 text-zinc-500">Selected node</div>
                          <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-emerald-200/85">
                            {JSON.stringify(ringFocus, null, 2)}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {(ringNet.cycles as { path?: string }[] | undefined)?.length ? (
                    <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
                      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-amber-400/90">
                        Payment cycles (sample)
                      </div>
                      <ul className="max-h-32 space-y-1 overflow-auto font-mono text-[10px] text-amber-200/80">
                        {((ringNet.cycles as { path: string }[]) || []).slice(0, 12).map((c, i) => (
                          <li key={i}>{c.path}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              ) : ringNet && ringNet.ok === false ? (
                <div className="rounded border border-amber-500/30 bg-amber-950/20 px-3 py-2 font-mono text-[11px] text-amber-200/90">
                  {String((ringNet as { error?: string }).error ?? 'Analysis failed')}
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}

      {tab === 'evidence' && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <EvidenceBoard caseId={activeCase?.id ?? null} />
        </div>
      )}

      {tab === 'table' && (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <div className="overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950/50">
            {!table ? (
              <div className="p-8 text-center font-mono text-[11px] text-zinc-600">No dataset bound to active case.</div>
            ) : (
              <div className="overflow-auto">
                <table className="w-full border-collapse text-left font-mono text-[11px]">
                  <thead>
                    <tr className="border-b border-zinc-800 bg-zinc-900/80">
                      {table.columns.map((c) => (
                        <th key={c} className="px-2 py-2 font-medium text-emerald-400/90">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {table.rows.map((row, i) => (
                      <tr key={i} className="border-b border-zinc-800/80 hover:bg-zinc-900/30">
                        {table.columns.map((c) => (
                          <td key={c} className="px-2 py-1.5 text-zinc-400">
                            {String(row[c] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
