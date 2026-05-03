import { create } from 'zustand'

export type LlmModalState = {
  open: boolean
  draft: string
  envDefault: string
  usingOverride: boolean
  err: string | null
  busy: boolean
  ollamaTags: string[]
  ollamaTagsHint: string | null
  apiRestartBusy: boolean
  apiRestartNote: { kind: 'ok' | 'err'; text: string } | null
}

type ShadowState = {
  chatThreadId: string
  rotateChatThread: () => void
  llm: LlmModalState
  setLlm: (p: Partial<LlmModalState>) => void
  resetLlmModal: () => void
}

const initialLlm = (): LlmModalState => ({
  open: false,
  draft: '',
  envDefault: '',
  usingOverride: false,
  err: null,
  busy: false,
  ollamaTags: [],
  ollamaTagsHint: null,
  apiRestartBusy: false,
  apiRestartNote: null,
})

export const useShadowStore = create<ShadowState>((set) => ({
  chatThreadId: crypto.randomUUID(),
  rotateChatThread: () => set({ chatThreadId: crypto.randomUUID() }),
  llm: initialLlm(),
  setLlm: (p) => set((s) => ({ llm: { ...s.llm, ...p } })),
  resetLlmModal: () => set({ llm: initialLlm() }),
}))
