import type { ReactNode } from 'react'

type Props = {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** Override default `max-w-lg` on the dialog panel (e.g. `max-w-3xl` for wide manifests). */
  panelClassName?: string
}

/** Layered panel with backdrop blur (forensic overlay pattern). */
export function ForensicModal({ open, onClose, title, children, panelClassName }: Props) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-zinc-950/55 backdrop-blur-sm"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="fc-modal-title"
        className={`relative max-h-[min(80vh,560px)] w-full overflow-auto rounded-lg border border-zinc-800 bg-[#09090b]/85 p-4 shadow-[0_0_40px_rgba(0,0,0,0.45)] backdrop-blur-md ${panelClassName ?? 'max-w-lg'}`}
      >
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 id="fc-modal-title" className="text-sm font-semibold tracking-tight text-zinc-100">
            {title}
          </h2>
          <button
            type="button"
            className="rounded-lg border border-transparent px-2 py-1 text-xs text-zinc-500 hover:border-zinc-700 hover:text-zinc-200"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        <div className="text-xs text-zinc-400">{children}</div>
      </div>
    </div>
  )
}
