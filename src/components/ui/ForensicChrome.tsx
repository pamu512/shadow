import type { ReactNode } from 'react'

type DotProps = {
  ok: boolean
  label: string
  className?: string
}

/** Pulsating health indicator (emerald when ok, amber when down). */
export function HealthPulsingDot({ ok, label, className = '' }: DotProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      title={`${label}: ${ok ? 'operational' : 'degraded'}`}
    >
      <span
        className={`relative inline-flex h-2 w-2 rounded-full ${
          ok ? 'bg-emerald-400 text-emerald-400 animate-status-pulse' : 'bg-amber-500 text-amber-500'
        }`}
        aria-hidden
      />
      <span className="select-none text-[11px] font-medium tracking-wide text-zinc-500">{label}</span>
    </span>
  )
}

export function GhostButton({
  children,
  className = '',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode; className?: string }) {
  return (
    <button
      type="button"
      className={`rounded-lg border border-transparent bg-transparent px-3 py-1.5 text-xs font-medium text-zinc-400 transition-colors hover:border-zinc-700 hover:bg-zinc-900/60 hover:text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-violet-500/60 disabled:pointer-events-none disabled:opacity-40 ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
