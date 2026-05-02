import { PinOff } from 'lucide-react'
import type { PinnedForensicPayload } from '../console/ForensicResultTranscriptCard'

type Props = {
  items: PinnedForensicPayload[]
  onUnpin: (id: string) => void
  caseName?: string | null
}

export function WorkbenchStrip({ items, onUnpin, caseName }: Props) {
  if (items.length === 0) return null

  return (
    <section className="border-b border-zinc-800 bg-gradient-to-b from-amber-950/12 to-[#0d0d0d] px-2.5 py-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-400/95">Workbench</div>
          <p className="mt-0.5 text-[10px] leading-snug text-zinc-500">
            Pinned from the agent transcript{caseName ? ` · ${caseName}` : ''}. Stays on this case.
          </p>
        </div>
        <span className="shrink-0 rounded border border-zinc-800 bg-zinc-950/80 px-2 py-0.5 font-mono text-[9px] text-zinc-500">
          {items.length} pin{items.length === 1 ? '' : 's'}
        </span>
      </div>
      <div className="flex max-h-[min(38vh,280px)] flex-col gap-2 overflow-y-auto pr-0.5 [scrollbar-width:thin]">
        {items.map((pin) => (
          <div
            key={pin.id}
            className="rounded-lg border border-amber-500/35 bg-zinc-950/70 px-3 py-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-xs font-semibold text-amber-100/95">{pin.title}</div>
                <p className="mt-1 line-clamp-4 text-[11px] leading-relaxed text-zinc-400">{pin.subtitle}</p>
              </div>
              <button
                type="button"
                className="shrink-0 rounded border border-zinc-700 p-1 text-zinc-500 hover:border-rose-500/50 hover:bg-rose-950/40 hover:text-rose-200"
                title="Remove from workbench"
                onClick={() => onUnpin(pin.id)}
              >
                <PinOff className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
