type RfiPayload = {
  kind?: string
  confidence_score?: number
  threshold?: number
  after_tool?: string | null
  prompt?: string
}

function parseRfi(content: string): RfiPayload | null {
  const t = content.trimStart()
  if (!t.startsWith('[RFI]')) return null
  const jsonPart = t.slice('[RFI]'.length).trim()
  try {
    const o: unknown = JSON.parse(jsonPart)
    return typeof o === 'object' && o !== null && !Array.isArray(o) ? (o as RfiPayload) : null
  } catch {
    return null
  }
}

type Props = {
  content: string
  onUploadMoreData: () => void
  onOverrideClear: () => void
}

export function LeadInvestigatorRFI({ content, onUploadMoreData, onOverrideClear }: Props) {
  const data = parseRfi(content)
  const conf = typeof data?.confidence_score === 'number' ? data.confidence_score : null
  const thr = typeof data?.threshold === 'number' ? data.threshold : null

  return (
    <div className="mt-1.5 w-full max-w-full rounded-lg border border-amber-500/35 bg-amber-950/[0.18] p-3 font-mono shadow-[0_0_24px_rgba(245,158,11,0.12)] backdrop-blur-md">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-400/95">Request for information</div>
      <div className="mb-1 text-xs font-semibold text-amber-50/95">Lead investigator handover</div>
      <p className="mb-3 text-[11px] leading-relaxed text-amber-100/85">
        {data?.prompt ??
          'The specialist agent is below its confidence threshold. Supply more context or override to continue.'}
      </p>
      {conf != null ? (
        <div className="mb-3 flex flex-wrap gap-3 text-[10px] text-amber-200/90">
          <span className="rounded border border-amber-500/30 bg-black/25 px-2 py-1 tabular-nums">
            Confidence <span className="font-bold">{conf.toFixed(2)}</span>
          </span>
          {thr != null ? (
            <span className="rounded border border-zinc-700/80 bg-zinc-950/60 px-2 py-1 tabular-nums text-zinc-400">
              Floor <span className="font-semibold text-zinc-200">{thr.toFixed(2)}</span>
            </span>
          ) : null}
          {data?.after_tool ? (
            <span className="rounded border border-zinc-700/80 bg-zinc-950/60 px-2 py-1 text-zinc-500">
              After <span className="text-zinc-300">{data.after_tool}</span>
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded-lg border border-cyan-500/45 bg-cyan-950/50 px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-cyan-100 hover:border-cyan-400/70 hover:bg-cyan-900/40"
          onClick={onUploadMoreData}
        >
          Upload more data
        </button>
        <button
          type="button"
          className="rounded-lg border border-zinc-600 bg-zinc-900/80 px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-zinc-200 hover:border-zinc-500 hover:bg-zinc-800/90"
          onClick={onOverrideClear}
        >
          Override &amp; clear
        </button>
      </div>
    </div>
  )
}

export function isRfiMessageContent(content: string): boolean {
  return content.trimStart().startsWith('[RFI]')
}
