import type { BackendStatus } from '../../shared/status/backendStatus'

export type StudioShellState = {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  backendStatus: BackendStatus
}
