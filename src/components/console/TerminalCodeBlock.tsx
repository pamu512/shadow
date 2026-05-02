import { useCallback, useState } from 'react'
import { executeCode } from '../../lib/api'

type Props = {
  lang: string
  code: string
  caseId: string | null | undefined
  onRunComplete: (summary: string) => void
}

function normalizeLang(lang: string): 'python' | 'r' | null {
  const l = lang.toLowerCase()
  if (l === 'python' || l === 'py') return 'python'
  if (l === 'r' || l === 'rlang') return 'r'
  return null
}

export function TerminalCodeBlock({ lang, code, caseId, onRunComplete }: Props) {
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const runnable = normalizeLang(lang)

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }, [code])

  const onRun = useCallback(async () => {
    if (!runnable) return
    setBusy(true)
    try {
      const r = await executeCode(runnable, code, caseId)
      const ok = (r.exit_code ?? 1) === 0 && !(r.violations && r.violations.length)
      const head = ok
        ? `Sandbox finished successfully (exit code ${r.exit_code}).`
        : `Sandbox finished with problems (exit code ${r.exit_code}).`
      const bits = [
        head,
        r.stdout?.trim() && `Printed output:\n${r.stdout.trim()}`,
        r.stderr?.trim() && `Error output:\n${r.stderr.trim()}`,
        (r.violations?.length ?? 0) > 0 && `Policy blocks:\n${r.violations!.join('\n')}`,
      ].filter(Boolean)
      onRunComplete(bits.join('\n\n'))
    } catch (e) {
      onRunComplete(`Run failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }, [runnable, code, caseId, onRunComplete])

  const title = lang && lang !== 'text' ? lang : 'snippet'

  return (
    <div className="my-2 overflow-hidden rounded-md border border-zinc-700 bg-zinc-950/90 ring-1 ring-zinc-800/80">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-800 bg-zinc-900/95 px-2 py-1 font-mono text-[10px]">
        <span className="truncate text-zinc-500">
          <span className="text-emerald-500/90">$</span> <span className="text-zinc-400">{title}</span>
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => void onCopy()}
            className="rounded border border-transparent px-2 py-0.5 text-zinc-500 transition-colors hover:border-zinc-600 hover:bg-zinc-800 hover:text-zinc-200"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
          {runnable ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onRun()}
              className="rounded border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-violet-200/90 transition-colors hover:border-violet-400/60 hover:bg-violet-500/15 disabled:opacity-50"
            >
              {busy ? '…' : 'Run in Sandbox'}
            </button>
          ) : null}
        </div>
      </div>
      <pre className="max-h-64 overflow-auto p-2.5 font-mono text-[11px] leading-snug text-zinc-300">{code}</pre>
    </div>
  )
}
