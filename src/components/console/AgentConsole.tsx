import { useCallback, useEffect, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { isRfiMessageContent, LeadInvestigatorRFI } from './LeadInvestigatorRFI'
import {
  AGENT_INJECT_EVENT,
  codeReview,
  fetchAtoUserIdSamples,
  fetchPersonas,
  sendChat,
  type AgentInjectDetail,
} from '../../lib/api'
import type { CaseOut, ChatMessage, PersonaListItem } from '../../lib/types'
import { GhostButton } from '../ui/ForensicChrome'
import { ForensicModal } from '../ui/ForensicModal'
import { columnMappingPreamble, getSessionColumnMapping, setSessionUserIdColumn } from '../../lib/sessionColumnMap'
import { extractTransactionIdCandidates, heuristicIdExtractor, latin1FromArrayBuffer } from '../../lib/disputeFilePrime'
import { requestWorkspaceTab } from '../../lib/workspaceEvents'
import { TerminalCodeBlock } from './TerminalCodeBlock'
import {
  isToolExecutionRenderable,
  parseBareJsonExecutionPayload,
  parseToolMessageContent,
  ToolExecutionBlock,
} from './ToolExecutionBlock'
import { ForensicResultTranscriptCard, type PinnedForensicPayload } from './ForensicResultTranscriptCard'
import { parseForensicTranscriptJson } from './parseForensicTranscriptJson'
import { renderTextWithEntityChips } from './EntityChip'
import { isHallucinatedAgentToolSnippet } from './agentToolSnippetGuard'
import {
  forensicTagForMessage,
  formatTerminalTime,
  hasFencedCode,
  humanSpeakerLabel,
  parseFencedCode,
  speakerAccentClass,
  type ForensicTag,
} from './terminalMessageUtils'

function BehavioralProfileLoadingCard() {
  return (
    <div className="my-2 rounded-lg border border-violet-500/35 bg-violet-950/15 px-3 py-3 font-sans">
      <div className="text-xs font-semibold text-violet-200">Behavioral profile loading…</div>
      <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
        History and ATO checks run on the server. You do not paste Python tool calls into this console.
      </p>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full w-[55%] animate-pulse rounded-full bg-gradient-to-r from-violet-500/70 to-cyan-500/60" />
      </div>
    </div>
  )
}

type Props = {
  activeCase: CaseOut | null
  onReviewResult: (original: string, suggested: string, notes: string) => void
  onPersonaChange?: (personaId: string) => void
  onPinForensic?: (item: PinnedForensicPayload) => void
}

type LineEntry = ChatMessage & { at: number }

function attachTimes(prev: LineEntry[], incoming: ChatMessage[]): LineEntry[] {
  const now = Date.now()
  return incoming.map((m, i) => {
    const old = prev[i]
    if (old && old.role === m.role && old.content === m.content) {
      return { ...m, at: old.at }
    }
    return { ...m, at: now + i * 2 }
  })
}

const TYPE_MS = 11

function stripTracebackFromProse(s: string): string {
  if (!/traceback \(most recent call last\)/i.test(s)) return s
  const idx = s.search(/traceback \(most recent call last\)/i)
  const head = s.slice(0, idx).trimEnd()
  return `${head}\n\n[Traceback hidden — see sidecar logs.]`
}

const WAREHOUSE_SQL_SNIPPETS = [
  'SELECT COUNT(*) AS n FROM dataset',
  'SELECT * FROM dataset LIMIT 100',
  'SELECT acc_id, COUNT(*) AS c FROM dataset GROUP BY 1 ORDER BY c DESC LIMIT 25',
  'SELECT * FROM dataset WHERE acc_id IS NOT NULL LIMIT 50',
  'Call get_dataset_schema_tool for this case',
  'Call search_historical_overlap_tool with entity_type "ip_address" and entity_id ""',
] as const

export function AgentConsole({ activeCase, onReviewResult, onPersonaChange, onPinForensic }: Props) {
  const [personaId, setPersonaId] = useState('general')
  const [personas, setPersonas] = useState<PersonaListItem[]>([])
  const [lines, setLines] = useState<LineEntry[]>([
    {
      role: 'assistant',
      content:
        'General Fraud Analyst · Expert lens active. Select a specialized persona above or issue a directive.',
      at: Date.now(),
    },
  ])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [fileDragActive, setFileDragActive] = useState(false)
  const colDragDepth = useRef(0)
  const [heuristicVerifyIds, setHeuristicVerifyIds] = useState<string[]>([])
  const [atoUserSamples, setAtoUserSamples] = useState<string[]>([])
  const [quickAtoUser, setQuickAtoUser] = useState('')
  const [columnMapperOpen, setColumnMapperOpen] = useState(false)
  const [mapperSuggestion, setMapperSuggestion] = useState('acc_id')
  const [formulaMode, setFormulaMode] = useState(false)
  const [twLen, setTwLen] = useState(0)
  const twTargetRef = useRef<string>('')
  const linesRef = useRef(lines)
  linesRef.current = lines
  const prevPersonaIdRef = useRef<string | null>(null)
  const prevCaseIdRef = useRef<string | null | undefined>(undefined)
  const pendingThreadResetRef = useRef(false)

  const activePersona = personas.find((p) => p.id === personaId) ?? null

  useEffect(() => {
    void fetchPersonas()
      .then(setPersonas)
      .catch(() => setPersonas([]))
  }, [])

  useEffect(() => {
    if (!activeCase?.id) {
      setAtoUserSamples([])
      setQuickAtoUser('')
      return
    }
    void fetchAtoUserIdSamples(activeCase.id)
      .then((r) => {
        if (r.ok && Array.isArray(r.user_ids)) setAtoUserSamples(r.user_ids)
        else setAtoUserSamples([])
      })
      .catch(() => setAtoUserSamples([]))
  }, [activeCase?.id])

  const welcomeText = (pid: string, list: PersonaListItem[]) => {
    const p = list.find((x) => x.id === pid)
    if (!p) {
      return 'Multi-agent graph online. Select an expert lens or issue a directive below.'
    }
    return `${p.display_name} · Expert lens active. Ready for fraud analytics directives.`
  }

  /** Refresh welcome when `/api/personas` resolves; omit personaId from deps so a lens switch is not overwritten. */
  useEffect(() => {
    setLines((prev) => {
      const userMsgs = prev.filter((l) => l.role === 'user')
      if (userMsgs.length > 0) return prev
      return [{ role: 'assistant', content: welcomeText(personaId, personas), at: Date.now() }]
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally personas-only; persona switches use prevPersonaIdRef effect
  }, [personas])

  useEffect(() => {
    if (prevPersonaIdRef.current === null) {
      prevPersonaIdRef.current = personaId
      return
    }
    if (prevPersonaIdRef.current === personaId) return
    prevPersonaIdRef.current = personaId
    setLines([{ role: 'assistant', content: welcomeText(personaId, personas), at: Date.now() }])
    pendingThreadResetRef.current = true
  }, [personaId, personas])

  /** New thread when the active case changes (including null ↔ case). */
  useEffect(() => {
    const cid = activeCase?.id ?? null
    if (prevCaseIdRef.current === undefined) {
      prevCaseIdRef.current = cid
      return
    }
    if (prevCaseIdRef.current === cid) return
    prevCaseIdRef.current = cid
    setLines([{ role: 'assistant', content: welcomeText(personaId, personas), at: Date.now() }])
    pendingThreadResetRef.current = true
  }, [activeCase?.id, personaId, personas])

  const resetChatToWelcome = useCallback(() => {
    setLines([{ role: 'assistant', content: welcomeText(personaId, personas), at: Date.now() }])
    pendingThreadResetRef.current = true
  }, [personaId, personas])

  const pushAssistant = useCallback((text: string) => {
    setLines((p) => [...p, { role: 'assistant', content: text, at: Date.now() }])
  }, [])

  const onRunSandboxComplete = useCallback((summary: string) => {
    setLines((p) => [...p, { role: 'assistant', content: summary, at: Date.now() }])
  }, [])

  const lastIdx = lines.length - 1
  const lastLine = lines[lastIdx]
  const lastAssistantFull = lastLine?.role === 'assistant' ? lastLine.content : ''
  const lastAssistantTag: ForensicTag =
    lastLine?.role === 'assistant' ? forensicTagForMessage('assistant', lastAssistantFull) : 'SYSTEM'
  const typewriterActive =
    Boolean(lastAssistantFull) &&
    !isRfiMessageContent(lastAssistantFull) &&
    !hasFencedCode(lastAssistantFull) &&
    !isToolExecutionRenderable(lastAssistantFull, lastAssistantTag === 'EXECUTION') &&
    !parseForensicTranscriptJson(lastAssistantFull) &&
    lastLine?.role === 'assistant'

  useEffect(() => {
    if (!typewriterActive) {
      setTwLen(lastAssistantFull.length)
      twTargetRef.current = ''
      return
    }
    if (twTargetRef.current === lastAssistantFull) return
    twTargetRef.current = lastAssistantFull
    setTwLen(0)
    let i = 0
    let timer: ReturnType<typeof setTimeout>
    const step = () => {
      i += 1
      if (i >= lastAssistantFull.length) {
        setTwLen(lastAssistantFull.length)
        return
      }
      setTwLen(i)
      timer = setTimeout(step, TYPE_MS)
    }
    timer = setTimeout(step, TYPE_MS)
    return () => clearTimeout(timer)
  }, [lastAssistantFull, typewriterActive, lastIdx])

  const sendWithText = useCallback(
    async (text: string, personaOverride?: string | null) => {
      const raw = text.trim()
      if (!raw) return
      const preamble = columnMappingPreamble(activeCase?.id)
      const t = preamble ? `${preamble}${raw}` : raw
      const effectivePersona = (personaOverride ?? personaId)?.trim() || personaId
      const snapshot = linesRef.current
      const userLine: LineEntry = { role: 'user', content: t, at: Date.now() }
      const nextChat: ChatMessage[] = [
        ...snapshot.map(({ role, content }) => ({ role, content })),
        { role: 'user', content: t },
      ]
      setLines((p) => [...p, userLine])
      setBusy(true)
      try {
        const threadReset = pendingThreadResetRef.current
        pendingThreadResetRef.current = false
        const res = await sendChat(nextChat, activeCase?.id, effectivePersona, threadReset)
        setLines((prev) => attachTimes(prev, res.messages))
      } catch (e) {
        setLines((p) => [
          ...p,
          {
            role: 'assistant',
            content: `ERR ${e instanceof Error ? e.message : String(e)}`,
            at: Date.now(),
          },
        ])
      } finally {
        setBusy(false)
      }
    },
    [activeCase?.id, personaId],
  )

  const retryAtoAutoMap = useCallback(() => {
    void sendWithText(
      'Call analyze_ato_risk_tool with user_id as an empty string and the same current_session_json so the server infers acc_id or user_id from the dataset schema.',
    )
  }, [sendWithText])

  const submitChat = useCallback(async () => {
    const t = input.trim()
    if (!t || busy) return
    setInput('')
    setHeuristicVerifyIds([])
    await sendWithText(t)
  }, [input, busy, sendWithText])

  useEffect(() => {
    const onInject = (e: Event) => {
      const d = (e as CustomEvent<AgentInjectDetail>).detail
      const text = d?.text?.trim()
      if (!text || busy) return
      const pid = d?.persona_id?.trim() || null
      void sendWithText(text, pid)
    }
    window.addEventListener(AGENT_INJECT_EVENT, onInject as EventListener)
    return () => window.removeEventListener(AGENT_INJECT_EVENT, onInject as EventListener)
  }, [busy, sendWithText])

  useEffect(() => {
    if (!activeCase?.id) {
      setColumnMapperOpen(false)
      return
    }
    if (getSessionColumnMapping(activeCase.id)) {
      setColumnMapperOpen(false)
      return
    }
    const rev = [...lines].reverse().find((l) => l.role === 'assistant')
    if (!rev) {
      setColumnMapperOpen(false)
      return
    }
    const tp = parseToolMessageContent(rev.content)
    const errRaw = tp?.payload.ok === false ? String(tp.payload.error ?? tp.payload.message ?? '') : ''
    const err = errRaw.toLowerCase()
    const prose = rev.content.toLowerCase()
    const looksMissingUser =
      (tp &&
        tp.payload.ok === false &&
        err.includes('user_id') &&
        (err.includes('required') || err.includes('field') || err.includes('resolve'))) ||
      (!tp &&
        prose.includes('user_id') &&
        (prose.includes('field required') || prose.includes('missing') || prose.includes('invoke')) &&
        !prose.includes('traceback'))
    if (!looksMissingUser) {
      setColumnMapperOpen(false)
      return
    }
    const cols = tp?.payload.available_columns
    let guess = 'acc_id'
    if (Array.isArray(cols)) {
      const hit = cols.map(String).find((c) => /acc|customer|account|member|uid/i.test(c))
      if (hit) guess = hit
    }
    setMapperSuggestion(guess)
    setColumnMapperOpen(true)
  }, [lines, activeCase?.id])

  const onDropCodeFile = async (f: File) => {
    const text = await f.text()
    const lang = f.name.endsWith('.R') || f.name.endsWith('.r') ? 'r' : 'python'
    setBusy(true)
    try {
      const r = await codeReview(text, lang, activeCase?.id)
      onReviewResult(r.original, r.suggested, r.notes)
      requestWorkspaceTab('diff')
      pushAssistant(
        `Code review finished (${lang === 'r' ? 'R' : 'Python'}). Open the workspace Diff tab to see suggested changes.`,
      )
    } catch (e) {
      pushAssistant(`Code review could not run: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const onDropKnowledge = async (f: File) => {
    const lower = f.name.toLowerCase()
    if (lower.endsWith('.py') || lower.endsWith('.r')) {
      await onDropCodeFile(f)
      return
    }
    if (lower.endsWith('.txt')) {
      const body = await f.text()
      const ids = extractTransactionIdCandidates(body)
      if (ids.length) {
        setHeuristicVerifyIds(ids)
        setInput(
          `Verify IDs & Investigate: candidate transaction id(s): ${ids.join(', ')}. Confirm each against "${f.name}" before running chargeback_trust_velocity_tool or build_representment_manifest_tool.`,
        )
        pushAssistant(
          `Knowledge drop: extracted ${ids.length} transaction id candidate(s) from text — ${ids.slice(0, 4).join(', ')}${ids.length > 4 ? '…' : ''}. Review the draft message below and send.`,
        )
      } else {
        setHeuristicVerifyIds([])
        pushAssistant(
          `Knowledge drop: read "${f.name}" but no transaction id pattern matched. Paste an order / txn id or re-export the dispute letter.`,
        )
      }
      return
    }
    if (lower.endsWith('.pdf')) {
      const buf = await f.arrayBuffer()
      const latin = latin1FromArrayBuffer(buf)
      const ids = heuristicIdExtractor(latin)
      if (ids.length) {
        const primary = ids[0]
        setHeuristicVerifyIds(ids)
        const extra =
          ids.length > 1
            ? `\n\nAdditional heuristic matches (verify which applies): ${ids.slice(1).join(', ')}.`
            : ''
        setInput(
          `I've detected Transaction ID ${primary}. Should I cross-reference this with the Dispute Desk?${extra}`,
        )
        pushAssistant(
          `Co-pilot: heuristic scan of "${f.name}" surfaced ${ids.length === 1 ? 'a transaction id' : `${ids.length} id candidates`}. Review the composer draft and confirm before sending.`,
        )
      } else {
        setHeuristicVerifyIds([])
        pushAssistant(
          `Knowledge drop: no transaction id found in "${f.name}" via heuristic scan. Try searchable text export or paste the transaction id.`,
        )
      }
      return
    }
    pushAssistant(`Unsupported drop: ${f.name}. Use .py, .R, .txt, or .pdf.`)
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col bg-[#0d0d0d]/98 font-sans text-zinc-200 backdrop-blur-sm">
      <div className="sticky top-0 z-30 flex shrink-0 items-center gap-2 border-b border-zinc-800 bg-[#0d0d0d]/95 px-2 py-1.5 backdrop-blur-md">
        <label className="flex min-w-0 flex-1 items-center gap-2">
          <span className="shrink-0 text-[10px] font-medium uppercase tracking-wider text-zinc-500">Lens</span>
          <select
            className="min-w-0 flex-1 cursor-pointer rounded-md border border-zinc-800 bg-zinc-900 py-1.5 pl-2 pr-8 text-[11px] font-medium text-zinc-200 shadow-inner focus:border-violet-500/50 focus:outline-none focus:ring-1 focus:ring-violet-500/35"
            value={personaId}
            onChange={(e) => {
              setPersonaId(e.target.value)
              onPersonaChange?.(e.target.value)
            }}
            aria-label="Investigative persona"
          >
            {personas.length === 0 ? (
              <option value="general">General Fraud Analyst</option>
            ) : (
              personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))
            )}
          </select>
        </label>
        <button
          type="button"
          disabled={busy}
          title="Clear transcript (persona unchanged)"
          aria-label="Clear chat"
          className="shrink-0 rounded-md border border-zinc-800 bg-zinc-900 p-2 text-zinc-400 transition-colors hover:border-zinc-700 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-40"
          onClick={resetChatToWelcome}
        >
          <RotateCcw className="h-4 w-4" aria-hidden />
        </button>
      </div>

      {activeCase?.persona_suggestion && activeCase.persona_suggestion.persona_id !== personaId ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800/80 bg-amber-500/[0.06] px-2 py-1.5">
          <span className="text-[10px] font-medium text-amber-300/95">Suggested lens</span>
          <span className="text-[10px] text-zinc-400">
            Fits <span className="font-semibold text-zinc-200">{activeCase.persona_suggestion.display_name}</span>
          </span>
          <button
            type="button"
            className="rounded border border-amber-500/40 bg-zinc-950/80 px-2 py-0.5 text-[10px] font-medium text-amber-100 hover:bg-amber-500/10"
            onClick={() => {
              const id = activeCase.persona_suggestion!.persona_id
              setPersonaId(id)
              onPersonaChange?.(id)
            }}
          >
            Use
          </button>
        </div>
      ) : null}

      <div
        className="relative flex min-h-0 flex-1 flex-col"
        onDragEnter={(e) => {
          e.preventDefault()
          if (![...e.dataTransfer.types].includes('Files')) return
          colDragDepth.current += 1
          setFileDragActive(true)
        }}
        onDragLeave={(e) => {
          e.preventDefault()
          const rel = e.relatedTarget as Node | null
          if (rel && (e.currentTarget as HTMLElement).contains(rel)) return
          colDragDepth.current = Math.max(0, colDragDepth.current - 1)
          if (colDragDepth.current === 0) setFileDragActive(false)
        }}
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
        }}
        onDrop={(e) => {
          e.preventDefault()
          colDragDepth.current = 0
          setFileDragActive(false)
          const f = e.dataTransfer.files[0]
          if (f) void onDropKnowledge(f)
        }}
      >
        {fileDragActive ? (
          <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center border-2 border-dashed border-fuchsia-500/45 bg-zinc-950/75 backdrop-blur-md">
            <div className="text-sm font-semibold tracking-tight text-fuchsia-100">Drop to ingest</div>
            <p className="mt-2 max-w-sm px-4 text-center text-[11px] leading-relaxed text-zinc-400">
              <span className="font-mono text-zinc-300">.py</span> / <span className="font-mono text-zinc-300">.R</span>{' '}
              → code review + Diff · <span className="font-mono text-zinc-300">.txt</span> /{' '}
              <span className="font-mono text-zinc-300">.pdf</span> → Dispute Desk co-pilot (heuristic id)
            </p>
          </div>
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-zinc-800/90 px-2 py-1">
          <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(52,211,153,0.5)]" aria-hidden />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Transcript</span>
          <span className="text-[10px] text-zinc-600">· newest at bottom</span>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-[#050507] px-3 py-2">
          {activeCase?.id && atoUserSamples.length > 0 ? (
            <div className="mb-3 rounded-lg border border-zinc-800/90 bg-zinc-950/60 px-3 py-2.5 font-sans">
              <label className="flex flex-col gap-1">
                <span className="text-[11px] font-medium text-zinc-500">Quick pick · user id (ATO)</span>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    className="min-w-[12rem] flex-1 cursor-pointer rounded-md border border-zinc-700/90 bg-zinc-900 py-1.5 pl-2 pr-8 text-xs text-zinc-200 focus:border-violet-500/60 focus:outline-none focus:ring-1 focus:ring-violet-500/40"
                    value={quickAtoUser}
                    onChange={(e) => {
                      const v = e.target.value
                      setQuickAtoUser(v)
                      if (v) {
                        setInput((prev) =>
                          prev.trim()
                            ? prev
                            : `Run analyze_ato_risk_tool for user_id "${v}" with this session JSON (fill lat/lon/timestamp): {}`,
                        )
                      }
                    }}
                  >
                    <option value="">Search user…</option>
                    {atoUserSamples.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="text-[10px] leading-snug text-zinc-600">
                  Choosing a row fills a starter message—edit the JSON, then send.
                </p>
              </label>
            </div>
          ) : null}
          <div className="divide-y divide-zinc-800/60">
            {lines.map((entry, i) => {
              const tag: ForensicTag = forensicTagForMessage(entry.role, entry.content)
              const timeStr = formatTerminalTime(entry.at)
              const speaker = humanSpeakerLabel(entry.role, tag)
              const isLastAssistant = i === lastIdx && entry.role === 'assistant'
              const full = entry.content
              const isRfi = entry.role === 'assistant' && isRfiMessageContent(full)
              const toolParsed =
                entry.role === 'assistant' && !isRfi
                  ? (parseToolMessageContent(full) ?? parseBareJsonExecutionPayload(full, tag))
                  : null
              const forensicParsed =
                entry.role === 'assistant' && !isRfi && !toolParsed ? parseForensicTranscriptJson(full) : null
              const useTw = isLastAssistant && typewriterActive && !toolParsed && !forensicParsed && !isRfi
              const shown = useTw ? full.slice(0, twLen) : full
              const segments =
                useTw && twLen < full.length ? [{ type: 'text' as const, value: shown }] : parseFencedCode(shown)
              const showCaret = useTw && twLen < full.length

              return (
                <div
                  key={`${i}-${entry.at}-${entry.content.slice(0, 24)}`}
                  className="grid grid-cols-[3.5rem_minmax(0,5.5rem)_1fr] items-start gap-x-2 gap-y-1 py-3 text-[13px] leading-relaxed text-zinc-300 first:pt-2 sm:grid-cols-[4rem_minmax(0,7rem)_1fr]"
                >
                  <div className="select-none pt-0.5 text-right font-mono text-[10px] tabular-nums text-zinc-500">
                    {timeStr}
                  </div>
                  <div
                    className={`select-none pt-0.5 text-xs font-semibold ${speakerAccentClass(entry.role, tag)}`}
                    title={entry.role === 'user' ? 'Your message' : 'Assistant or automated step'}
                  >
                    {speaker}
                  </div>
                  <div className="min-w-0">
                  {isRfi ? (
                    <LeadInvestigatorRFI
                      content={full}
                      onUploadMoreData={() => {
                        setInput((s) => (s.trim() ? s : 'Additional evidence for Lead Investigator: '))
                      }}
                      onOverrideClear={() => {
                        setLines((p) => p.filter((l) => !isRfiMessageContent(l.content)))
                      }}
                    />
                  ) : toolParsed ? (
                    <ToolExecutionBlock
                      toolName={toolParsed.toolName}
                      payload={toolParsed.payload}
                      rawBody={toolParsed.rawBody}
                      onRetryAtoAutoMap={retryAtoAutoMap}
                      onPinWorkbench={activeCase?.id ? onPinForensic : undefined}
                    />
                  ) : forensicParsed ? (
                    <ForensicResultTranscriptCard
                      payload={forensicParsed}
                      onPin={activeCase?.id && onPinForensic ? onPinForensic : undefined}
                    />
                  ) : (
                    <>
                      {segments.map((seg, si) =>
                        seg.type === 'text' ? (
                          <span key={si} className="whitespace-pre-wrap break-words">
                            {renderTextWithEntityChips(stripTracebackFromProse(seg.value))}
                          </span>
                        ) : isHallucinatedAgentToolSnippet(seg.value, seg.lang) ? (
                          <BehavioralProfileLoadingCard key={si} />
                        ) : (
                          <TerminalCodeBlock
                            key={si}
                            lang={seg.lang}
                            code={seg.value}
                            caseId={activeCase?.id}
                            onRunComplete={onRunSandboxComplete}
                          />
                        ),
                      )}
                      {showCaret ? (
                        <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 bg-cyan-400/90 animate-pulse align-text-bottom" />
                      ) : null}
                    </>
                  )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <div className="border-t border-zinc-800 p-3">
        {activePersona?.suggested_queries?.length ? (
          <div className="mb-2">
            <div className="mb-1 text-[9px] font-medium uppercase tracking-wider text-zinc-600">Quick prompts</div>
            <div className="-mx-0.5 flex gap-1.5 overflow-x-auto px-0.5 pb-1 [scrollbar-width:thin]">
              {activePersona.suggested_queries.map((q) => (
                <button
                  key={q}
                  type="button"
                  disabled={busy}
                  className="max-w-[min(280px,85vw)] shrink-0 rounded-full border border-zinc-700/90 bg-zinc-900/80 px-2.5 py-1 text-left text-[11px] leading-snug text-zinc-300 hover:border-violet-500/45 hover:bg-violet-950/25 hover:text-zinc-100 disabled:opacity-40"
                  onClick={() => void sendWithText(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <datalist id="warehouse-sql-hints">
          {WAREHOUSE_SQL_SNIPPETS.map((q) => (
            <option key={q} value={q} />
          ))}
        </datalist>
        <div className="mb-1.5">
          <input
            list="warehouse-sql-hints"
            className="w-full rounded-md border border-zinc-800/90 bg-zinc-900/70 px-2.5 py-1.5 font-mono text-[10px] text-zinc-300 placeholder:text-zinc-600 focus:border-violet-500/40 focus:outline-none"
            placeholder="Global Warehouse SQL / tool stub — pick a suggestion to append"
            aria-label="Warehouse SQL autocomplete"
            onChange={(e) => {
              const v = e.target.value.trim()
              if (!WAREHOUSE_SQL_SNIPPETS.includes(v as (typeof WAREHOUSE_SQL_SNIPPETS)[number])) return
              setInput((p) => (p.trim() ? `${p.trim()}\n${v}` : v))
              e.target.value = ''
            }}
          />
        </div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] font-medium text-zinc-600">Directive composer</span>
          <button
            type="button"
            className={`rounded-md border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${
              formulaMode
                ? 'border-fuchsia-500/50 bg-fuchsia-950/40 text-fuchsia-100'
                : 'border-zinc-700 bg-zinc-900 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
            }`}
            onClick={() => setFormulaMode((v) => !v)}
          >
            {formulaMode ? 'Formula mode · on' : 'Formula mode'}
          </button>
        </div>
        {heuristicVerifyIds.length > 0 ? (
          <div className="mb-2 rounded-md border border-amber-500/35 bg-amber-950/20 px-2 py-1.5">
            <div className="text-[9px] font-semibold uppercase tracking-wider text-amber-400/95">Verify before send</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {heuristicVerifyIds.map((id) => (
                <span
                  key={id}
                  className="rounded border border-amber-500/45 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] font-medium text-amber-100"
                >
                  {id}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        <div className="relative flex items-stretch gap-2 rounded-lg border border-zinc-800 bg-zinc-950/90 shadow-inner backdrop-blur-md">
          <span className="flex select-none items-start pt-2.5 pl-3 text-sm font-medium text-fuchsia-500/90">&gt;_</span>
          <textarea
            className={`min-w-0 flex-1 resize-y border-0 bg-transparent py-2 pr-2 text-xs leading-relaxed text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-0 ${
              formulaMode ? 'min-h-[10rem] max-h-[min(50vh,420px)]' : 'min-h-[2.75rem] max-h-40'
            }`}
            rows={Math.min(formulaMode ? 24 : 10, Math.max(formulaMode ? 6 : 2, input.split('\n').length || 1))}
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              if (heuristicVerifyIds.length && !heuristicVerifyIds.some((id) => e.target.value.includes(id))) {
                setHeuristicVerifyIds([])
              }
            }}
            onDragOver={(e) => {
              e.preventDefault()
              e.stopPropagation()
              e.dataTransfer.dropEffect = 'copy'
            }}
            onDrop={(e) => {
              e.preventDefault()
              e.stopPropagation()
              colDragDepth.current = 0
              setFileDragActive(false)
              const f = e.dataTransfer.files[0]
              if (f) void onDropKnowledge(f)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void submitChat()
              }
            }}
            placeholder="Message the agent… (Shift+Enter for newline) · drop files here"
            aria-label="Message to agent"
          />
          <GhostButton
            disabled={busy}
            onClick={() => void submitChat()}
            className="self-start rounded-none border-0 border-l border-zinc-800 !px-4 !py-2.5 hover:!bg-zinc-900"
          >
            {busy ? '…' : 'Send'}
          </GhostButton>
        </div>
      </div>
      </div>
      <ForensicModal open={columnMapperOpen} onClose={() => setColumnMapperOpen(false)} title="Data mapper">
        <p className="leading-relaxed text-zinc-300">
          A tool could not resolve <span className="font-mono text-amber-200">user_id</span> on this dataset. Map it to
          a real column for the rest of this browser session?
        </p>
        <p className="mt-3 text-zinc-500">
          Suggested column: <span className="font-mono text-emerald-200">{mapperSuggestion}</span>
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy || !activeCase?.id}
            className="rounded-lg border border-emerald-500/50 bg-emerald-950/40 px-4 py-2 text-sm font-semibold text-emerald-100 hover:bg-emerald-900/45 disabled:opacity-40"
            onClick={() => {
              if (!activeCase?.id) return
              setSessionUserIdColumn(activeCase.id, mapperSuggestion, 'user_id')
              setColumnMapperOpen(false)
              void sendWithText(
                `Run get_dataset_schema_tool, then repeat the failed step using column "${mapperSuggestion}" as the account / user identifier (logical user_id).`,
              )
            }}
          >
            Yes — remember for this session
          </button>
          <button
            type="button"
            className="rounded-lg border border-zinc-600 bg-zinc-900 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
            onClick={() => setColumnMapperOpen(false)}
          >
            Dismiss
          </button>
        </div>
      </ForensicModal>
    </div>
  )
}
