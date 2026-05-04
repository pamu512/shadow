import { useEffect, useState } from 'react'
import { Command } from 'cmdk'
import { useShadowStore } from '../../stores/shadowStore'
import { restartShadowSidecar } from '../../lib/api'
import { toast } from 'sonner'
import { useHealthQuery } from '../../hooks/useHealthQuery'

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const setLlm = useShadowStore((s) => s.setLlm)
  const rotateChatThread = useShadowStore((s) => s.rotateChatThread)
  const { refresh } = useHealthQuery()

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((open) => !open)
      }
    }
    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[20vh] backdrop-blur-sm">
      <div className="w-full max-w-xl overflow-hidden rounded-xl border border-zinc-800 bg-[#0c0c0f] shadow-2xl">
        <Command
          className="w-full"
          loop
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false)
          }}
        >
          <Command.Input
            autoFocus
            placeholder="Type a command or search..."
            className="w-full border-b border-zinc-800 bg-transparent px-4 py-4 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none"
          />
          <Command.List className="max-h-[300px] overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-zinc-500">No results found.</Command.Empty>

            <Command.Group heading="System" className="text-xs font-medium text-zinc-500 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              <Command.Item
                onSelect={() => {
                  setOpen(false)
                  setLlm({ open: true })
                }}
                className="flex cursor-pointer items-center rounded-md px-2 py-2 text-sm text-zinc-200 aria-selected:bg-violet-500/20 aria-selected:text-violet-200"
              >
                Change Ollama Model
              </Command.Item>
              <Command.Item
                onSelect={() => {
                  setOpen(false)
                  const promise = restartShadowSidecar().then(async (msg) => {
                    await refresh()
                    return msg
                  })
                  toast.promise(promise, {
                    loading: 'Restarting API...',
                    success: (msg) => msg,
                    error: 'Failed to restart API',
                  })
                }}
                className="flex cursor-pointer items-center rounded-md px-2 py-2 text-sm text-zinc-200 aria-selected:bg-violet-500/20 aria-selected:text-violet-200"
              >
                Restart Shadow Sidecar
              </Command.Item>
            </Command.Group>

            <Command.Group heading="Chat" className="mt-2 text-xs font-medium text-zinc-500 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              <Command.Item
                onSelect={() => {
                  setOpen(false)
                  rotateChatThread()
                  toast.success('Chat thread reset')
                }}
                className="flex cursor-pointer items-center rounded-md px-2 py-2 text-sm text-zinc-200 aria-selected:bg-violet-500/20 aria-selected:text-violet-200"
              >
                Clear Chat Thread
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  )
}
