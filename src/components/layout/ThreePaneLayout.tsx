import type { Dispatch, SetStateAction } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { WorkspaceDataProvider } from '../../context/WorkspaceDataContext'
import { CaseFilesPanel } from '../sidebar/CaseFilesPanel'
import { AgentConsole } from '../console/AgentConsole'
import type { PinnedForensicPayload } from '../console/ForensicResultTranscriptCard'
import { WorkspaceViewer } from '../viewer/WorkspaceViewer'
import type { CaseOut } from '../../lib/types'

type LayoutProps = {
  activeCase: CaseOut | null
  setActiveCase: Dispatch<SetStateAction<CaseOut | null>>
  review: { original: string; suggested: string; notes: string } | null
  setReview: (r: { original: string; suggested: string; notes: string } | null) => void
}

const paneChrome =
  'relative min-h-0 bg-[#0d0d0d] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)] before:pointer-events-none before:absolute before:left-0 before:top-0 before:bottom-0 before:w-px before:bg-zinc-800/90 before:content-[\'\'] after:pointer-events-none after:absolute after:right-0 after:top-0 after:bottom-0 after:w-px after:bg-black/40 after:content-[\'\']'

const LEGACY_PINNED_KEY = 'shadow:pinned-forensics-v1'
const CASE_PINNED_KEY = 'shadow:pinned-forensics-by-case-v1'
const MIGRATED_FLAG = 'shadow:pinned-forensics-migrated-v1'

type PinStore = Record<string, PinnedForensicPayload[]>

function isPinnedPayload(x: unknown): x is PinnedForensicPayload {
  return Boolean(
    x &&
      typeof x === 'object' &&
      typeof (x as PinnedForensicPayload).id === 'string' &&
      typeof (x as PinnedForensicPayload).title === 'string',
  )
}

function readPinStore(): PinStore {
  try {
    const raw = sessionStorage.getItem(CASE_PINNED_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    const out: PinStore = {}
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(v)) continue
      const cleaned = v.filter(isPinnedPayload).slice(0, 12)
      if (cleaned.length) out[k] = cleaned
    }
    return out
  } catch {
    return {}
  }
}

function writePinStore(store: PinStore) {
  try {
    sessionStorage.setItem(CASE_PINNED_KEY, JSON.stringify(store))
  } catch {
    /* ignore */
  }
}

function migrateLegacyPinsIfNeeded(): void {
  try {
    if (sessionStorage.getItem(MIGRATED_FLAG)) return
    const legacyRaw = sessionStorage.getItem(LEGACY_PINNED_KEY)
    if (!legacyRaw) {
      sessionStorage.setItem(MIGRATED_FLAG, '1')
      return
    }
    const parsed = JSON.parse(legacyRaw) as unknown
    const arr = Array.isArray(parsed) ? parsed.filter(isPinnedPayload).slice(0, 12) : []
    const store = readPinStore()
    if (arr.length && !store.__legacy__) {
      store.__legacy__ = arr
      writePinStore(store)
    }
    sessionStorage.removeItem(LEGACY_PINNED_KEY)
    sessionStorage.setItem(MIGRATED_FLAG, '1')
  } catch {
    sessionStorage.setItem(MIGRATED_FLAG, '1')
  }
}

function pinsForCase(caseId: string, store: PinStore): PinnedForensicPayload[] {
  const direct = store[caseId]
  if (direct?.length) return direct
  const leg = store.__legacy__
  if (leg?.length) {
    const next = { ...store, [caseId]: leg }
    delete next.__legacy__
    writePinStore(next)
    return leg
  }
  return []
}

export function ThreePaneLayout({ activeCase, setActiveCase, review, setReview }: LayoutProps) {
  const [agentPersonaId, setAgentPersonaId] = useState('general')
  const [pinnedForensics, setPinnedForensics] = useState<PinnedForensicPayload[]>([])
  const activeCaseIdRef = useRef<string | null>(null)
  activeCaseIdRef.current = activeCase?.id ?? null

  useEffect(() => {
    migrateLegacyPinsIfNeeded()
  }, [])

  useEffect(() => {
    const id = activeCase?.id ?? null
    if (!id) {
      setPinnedForensics([])
      return
    }
    setPinnedForensics(pinsForCase(id, readPinStore()))
  }, [activeCase?.id])

  const persistPinsForActiveCase = useCallback((next: PinnedForensicPayload[]) => {
    const cid = activeCaseIdRef.current
    if (!cid) return
    const store = readPinStore()
    store[cid] = next
    writePinStore(store)
  }, [])

  const onPinForensic = useCallback(
    (item: PinnedForensicPayload) => {
      setPinnedForensics((p) => {
        const merged = [item, ...p].filter((x, i, a) => a.findIndex((y) => y.id === x.id) === i).slice(0, 12)
        persistPinsForActiveCase(merged)
        return merged
      })
    },
    [persistPinsForActiveCase],
  )

  const onUnpinForensic = useCallback(
    (id: string) => {
      setPinnedForensics((p) => {
        const merged = p.filter((x) => x.id !== id)
        persistPinsForActiveCase(merged)
        return merged
      })
    },
    [persistPinsForActiveCase],
  )

  return (
    <WorkspaceDataProvider>
      <div className="grid h-full w-full min-h-0 grid-cols-[minmax(272px,1fr)_1.85fr_minmax(320px,1.15fr)] gap-px bg-[#0d0d0d]">
        <div className={paneChrome}>
          <CaseFilesPanel activeId={activeCase?.id ?? null} onActiveChange={setActiveCase} />
        </div>
        <div className={`${paneChrome} border-x border-zinc-900/80 flex min-h-0 min-w-0`}>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <AgentConsole
              activeCase={activeCase}
              onReviewResult={(o, s, n) => setReview({ original: o, suggested: s, notes: n })}
              onPersonaChange={setAgentPersonaId}
              onPinForensic={onPinForensic}
            />
          </div>
        </div>
        <div className={paneChrome}>
          <WorkspaceViewer
            activeCase={activeCase}
            review={review}
            onActivateCase={setActiveCase}
            agentPersonaId={agentPersonaId}
            workbenchPins={pinnedForensics}
            onWorkbenchUnpin={onUnpinForensic}
          />
        </div>
      </div>
    </WorkspaceDataProvider>
  )
}
