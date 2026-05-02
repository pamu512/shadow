import type { ReactNode } from 'react'

function JsonValue({ value, depth }: { value: unknown; depth: number }): ReactNode {
  const pad = depth * 14

  if (value === null) {
    return <span className="text-zinc-500">null</span>
  }
  if (typeof value === 'boolean') {
    return <span className="text-violet-400">{String(value)}</span>
  }
  if (typeof value === 'number') {
    return <span className="text-amber-400 tabular-nums">{value}</span>
  }
  if (typeof value === 'string') {
    return <span className="text-emerald-400/90">&quot;{value}&quot;</span>
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-zinc-500">[]</span>
    }
    return (
      <span className="block">
        <span className="text-zinc-600">[</span>
        {value.map((item, i) => (
          <div key={i} className="block font-mono text-[11px] leading-relaxed" style={{ paddingLeft: pad + 14 }}>
            <JsonValue value={item} depth={depth + 1} />
            {i < value.length - 1 ? <span className="text-zinc-600">,</span> : null}
          </div>
        ))}
        <span className="text-zinc-600">]</span>
      </span>
    )
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) {
      return <span className="text-zinc-600">{'{}'}</span>
    }
    return (
      <span className="block">
        <span className="text-zinc-600">{'{'}</span>
        {entries.map(([k, v], i) => (
          <div key={`${k}-${i}`} className="block" style={{ paddingLeft: pad + 14 }}>
            <span className="font-mono text-[11px] text-fuchsia-400/90">&quot;{k}&quot;</span>
            <span className="text-zinc-600">: </span>
            <JsonValue value={v} depth={depth + 1} />
            {i < entries.length - 1 ? <span className="text-zinc-600">,</span> : null}
          </div>
        ))}
        <span className="text-zinc-600">{'}'}</span>
      </span>
    )
  }

  return <span className="text-zinc-500">{String(value)}</span>
}

/** Structured JSON tree with syntax-style highlighting. */
export function JsonTreeManifest({ jsonText }: { jsonText: string }) {
  let parsed: unknown
  try {
    parsed = JSON.parse(jsonText)
  } catch {
    return <pre className="whitespace-pre-wrap font-mono text-[11px] text-amber-200/80">{jsonText}</pre>
  }

  return (
    <div className="rounded-lg border border-zinc-800/80 bg-zinc-950/90 p-3 font-mono text-[11px] leading-relaxed text-zinc-300">
      <JsonValue value={parsed} depth={0} />
    </div>
  )
}
