import type { CaseStatus } from '../../lib/types'

function WarningGlyph({ className = 'h-3 w-3 shrink-0 text-red-400' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 10-2 0 1 1 0 002 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
        clipRule="evenodd"
      />
    </svg>
  )
}

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  if (status === 'INVESTIGATING') {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-violet-500/25 bg-violet-500/[0.12] px-2 py-0.5 backdrop-blur-sm">
        <span
          className="h-1.5 w-1.5 shrink-0 rounded-full bg-fuchsia-400 text-fuchsia-400 shadow-[0_0_8px] shadow-fuchsia-500/70 animate-status-pulse"
          aria-hidden
        />
        <span className="text-[10px] font-medium tracking-wide text-violet-200/95">Investigating</span>
      </span>
    )
  }
  if (status === 'FLAGGED') {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-md border-2 border-red-500 bg-red-950/25 px-2 py-0.5 shadow-[0_0_14px_rgba(239,68,68,0.4)]">
        <WarningGlyph />
        <span className="text-[10px] font-semibold uppercase tracking-wide text-red-200">Flagged</span>
      </span>
    )
  }
  return (
    <span className="inline-flex shrink-0 items-center rounded-full border border-emerald-500/10 bg-emerald-500/[0.05] px-2 py-0.5 opacity-55">
      <span className="text-[10px] font-medium tracking-wide text-emerald-400/55">Cleared</span>
    </span>
  )
}
