import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Copy, Crosshair, Database, ShieldOff } from 'lucide-react'
import { AGENT_INJECT_EVENT, type AgentInjectDetail } from '../../lib/api'

export type EntityKind = 'ip' | 'user' | 'fingerprint' | 'other'

type Props = {
  value: string
  kind: EntityKind
}

function warehouseInjectQuery(entityType: string, entityId: string): string {
  return (
    `Call search_historical_overlap_tool with entity_type "${entityType}" and entity_id ` +
    JSON.stringify(entityId) +
    ` to scan the Global Warehouse for prior cases.`
  )
}

export function EntityChip({ value, kind }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const inject = useCallback((text: string) => {
    window.dispatchEvent(new CustomEvent<AgentInjectDetail>(AGENT_INJECT_EVENT, { detail: { text } }))
    setOpen(false)
  }, [])

  const entityType =
    kind === 'ip' ? 'ip_address' : kind === 'user' ? 'user_id' : kind === 'fingerprint' ? 'device_id' : 'user_id'

  const border =
    kind === 'ip'
      ? 'border-cyan-500/40 bg-cyan-950/40 text-cyan-100'
      : kind === 'user'
        ? 'border-violet-500/40 bg-violet-950/35 text-violet-100'
        : kind === 'fingerprint'
          ? 'border-amber-500/40 bg-amber-950/35 text-amber-100'
          : 'border-zinc-600 bg-zinc-900/80 text-zinc-200'

  return (
    <span ref={ref} className="relative inline align-baseline">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`mx-0.5 inline max-w-[14rem] truncate rounded border px-1.5 py-px font-mono text-[10px] font-medium transition-colors hover:brightness-110 ${border}`}
        title="Entity actions"
      >
        {value}
      </button>
      {open ? (
        <span
          className="absolute left-0 top-full z-50 mt-1 flex min-w-[12rem] flex-col rounded-md border border-zinc-700 bg-[#0d0d0d] py-1 shadow-xl shadow-black/60"
          role="menu"
        >
          <button
            type="button"
            role="menuitem"
            className="flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-zinc-200 hover:bg-zinc-800/90"
            onClick={() => inject(warehouseInjectQuery(entityType, value))}
          >
            <Database className="h-3.5 w-3.5 shrink-0 text-cyan-400" aria-hidden />
            Cross-reference in Global Warehouse
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-zinc-200 hover:bg-zinc-800/90"
            onClick={() =>
              inject(
                `Pivot this investigation to entity ${JSON.stringify(value)} (${kind}). Cross-reference in the warehouse, then summarize risk for this ${kind === 'ip' ? 'IP' : kind === 'fingerprint' ? 'device / fingerprint' : 'user id'} as the primary lens.`,
              )
            }
          >
            <Crosshair className="h-3.5 w-3.5 shrink-0 text-fuchsia-400" aria-hidden />
            Pivot investigation here
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-zinc-200 hover:bg-zinc-800/90"
            onClick={() =>
              inject(
                `Emit a lead to blocklist / review entity ${kind === 'ip' ? 'IP' : kind === 'fingerprint' ? 'device' : 'user'} ` +
                  JSON.stringify(value) +
                  ` (operator intent: add to blocklist workflow).`,
              )
            }
          >
            <ShieldOff className="h-3.5 w-3.5 shrink-0 text-rose-400" aria-hidden />
            Add to blacklist (lead)
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-zinc-200 hover:bg-zinc-800/90"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(value)
              } catch {
                /* ignore */
              }
              setOpen(false)
            }}
          >
            <Copy className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-hidden />
            Copy value
          </button>
        </span>
      ) : null}
    </span>
  )
}

const IPV4 = /^(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})$/

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function classify(token: string): EntityKind {
  if (IPV4.test(token)) return 'ip'
  if (UUID.test(token)) return 'user'
  if (token.length >= 24 && /^[a-f0-9]+$/i.test(token)) return 'fingerprint'
  if (/^acc[_-][a-z0-9]{2,}$/i.test(token)) return 'user'
  if (/^u[_-]?[a-z0-9]+$/i.test(token) || /^usr[_-]?\d+/i.test(token) || /^\d{6,}$/.test(token)) return 'user'
  return 'other'
}

/** IPs, UUIDs, long hex fingerprints, u_* / acc_* style ids */
const ENTITY_RE =
  /\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b|\b[a-f0-9]{24,128}\b|\bacc[_-][a-z0-9]{2,}\b|\bu[_-]?[a-z0-9]{4,}\b/gi

export function renderTextWithEntityChips(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  const re = new RegExp(ENTITY_RE.source, 'gi')
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const raw = m[0]
    out.push(<EntityChip key={`${m.index}-${raw.slice(0, 16)}`} value={raw} kind={classify(raw)} />)
    last = m.index + raw.length
  }
  if (last < text.length) out.push(text.slice(last))
  if (out.length === 0) return [text]
  return out
}
