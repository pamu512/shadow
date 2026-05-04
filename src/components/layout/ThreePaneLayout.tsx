import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Dispatch, SetStateAction } from 'react'
import { useCallback, useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { WorkspaceDataProvider } from '../../context/WorkspaceDataContext'
import { CaseFilesPanel } from '../sidebar/CaseFilesPanel'
import { AgentConsole } from '../console/AgentConsole'
import type { PinnedForensicPayload } from '../../lib/types'
import { WorkspaceViewer } from '../viewer/WorkspaceViewer'
import type { CaseOut } from '../../lib/types'
import { fetchWorkbenchPins, putWorkbenchPins } from '../../lib/api'

type LayoutProps = {
  activeCase: CaseOut | null
  setActiveCase: Dispatch<SetStateAction<CaseOut | null>>
  review: { original: string; suggested: string; notes: string } | null
  setReview: (r: { original: string; suggested: string; notes: string } | null) => void
}

const paneChrome =
  'relative min-h-0 bg-[#0d0d0d] shadow-[inset_0_1px_0_0_rgba(255,255,255,0.03)] before:pointer-events-none before:absolute before:left-0 before:top-0 before:bottom-0 before:w-px before:bg-zinc-800/90 before:content-[\'\'] after:pointer-events-none after:absolute after:right-0 after:top-0 after:bottom-0 after:w-px after:bg-black/40 after:content-[\'\']'

function isPinnedPayload(x: unknown): x is PinnedForensicPayload {
  return Boolean(
    x &&
      typeof x === 'object' &&
      typeof (x as PinnedForensicPayload).id === 'string' &&
      typeof (x as PinnedForensicPayload).title === 'string',
  )
}

export function ThreePaneLayout({ activeCase, setActiveCase, review, setReview }: LayoutProps) {
  const [agentPersonaId, setAgentPersonaId] = useState('general')
  const queryClient = useQueryClient()

  const { data: pinsData } = useQuery({
    queryKey: ['workbenchPins', activeCase?.id],
    queryFn: async () => {
      if (!activeCase?.id) return { pins: [] }
      const res = await fetchWorkbenchPins(activeCase.id)
      const raw = Array.isArray(res.pins) ? res.pins : []
      return { pins: raw.filter(isPinnedPayload).slice(0, 12) }
    },
    enabled: !!activeCase?.id,
  })

  const pinnedForensics = pinsData?.pins ?? []

  const updatePinsMutation = useMutation({
    mutationFn: async (next: PinnedForensicPayload[]) => {
      if (!activeCase?.id) return { pins: [] }
      return putWorkbenchPins(activeCase.id, next)
    },
    onMutate: async (next) => {
      if (!activeCase?.id) return
      await queryClient.cancelQueries({ queryKey: ['workbenchPins', activeCase.id] })
      const previous = queryClient.getQueryData(['workbenchPins', activeCase.id])
      queryClient.setQueryData(['workbenchPins', activeCase.id], { pins: next })
      return { previous }
    },
    onError: (_err, _next, context) => {
      if (activeCase?.id && context?.previous) {
        queryClient.setQueryData(['workbenchPins', activeCase.id], context.previous)
      }
    },
  })

  const onPinForensic = useCallback(
    (item: PinnedForensicPayload) => {
      const merged = [item, ...pinnedForensics].filter((x, i, a) => a.findIndex((y) => y.id === x.id) === i).slice(0, 12)
      updatePinsMutation.mutate(merged)
    },
    [pinnedForensics, updatePinsMutation],
  )

  const onUnpinForensic = useCallback(
    (id: string) => {
      const merged = pinnedForensics.filter((x) => x.id !== id)
      updatePinsMutation.mutate(merged)
    },
    [pinnedForensics, updatePinsMutation],
  )

  return (
    <WorkspaceDataProvider>
      <PanelGroup direction="horizontal" className="h-full w-full min-h-0 bg-[#0d0d0d]">
        <Panel defaultSize={20} minSize={15} className={paneChrome}>
          <CaseFilesPanel activeId={activeCase?.id ?? null} onActiveChange={setActiveCase} />
        </Panel>
        <PanelResizeHandle className="w-1 bg-zinc-900/80 hover:bg-violet-500/50 transition-colors cursor-col-resize z-10" />
        <Panel defaultSize={40} minSize={25} className={`${paneChrome} flex min-h-0 min-w-0`}>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <AgentConsole
              activeCase={activeCase}
              onReviewResult={(o, s, n) => setReview({ original: o, suggested: s, notes: n })}
              onPersonaChange={setAgentPersonaId}
              onPinForensic={onPinForensic}
            />
          </div>
        </Panel>
        <PanelResizeHandle className="w-1 bg-zinc-900/80 hover:bg-violet-500/50 transition-colors cursor-col-resize z-10" />
        <Panel defaultSize={40} minSize={25} className={paneChrome}>
          <WorkspaceViewer
            activeCase={activeCase}
            review={review}
            onActivateCase={setActiveCase}
            agentPersonaId={agentPersonaId}
            workbenchPins={pinnedForensics}
            onWorkbenchUnpin={onUnpinForensic}
          />
        </Panel>
      </PanelGroup>
    </WorkspaceDataProvider>
  )
}
