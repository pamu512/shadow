/** Dispatch from AgentConsole / tools; WorkspaceViewer listens to switch tabs. */
export const WORKSPACE_TAB_EVENT = 'shadow-workspace-tab'

export function requestWorkspaceTab(tab: string) {
  window.dispatchEvent(new CustomEvent(WORKSPACE_TAB_EVENT, { detail: { tab } }))
}
