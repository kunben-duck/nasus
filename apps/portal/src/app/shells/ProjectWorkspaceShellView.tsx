import { useState } from 'react'
import type { ComponentProps, ReactNode } from 'react'

import type { BackendStatus } from '../../shared/status/backendStatus'
import { ProjectWorkspaceSidebar } from './ProjectWorkspaceSidebar'
import { StudioTermsBar } from './StudioTermsBar'
import type { StudioShellState } from './StudioShellTypes'
import { useSettingsPopover } from './useSettingsPopover'

type ProjectWorkspaceSidebarProject = ComponentProps<typeof ProjectWorkspaceSidebar>['project']

export function ProjectWorkspaceShellView({
  project,
  backendStatus,
  backToDashboard,
  rightPanel,
  renderSettingsLayer,
  children,
}: {
  project?: ProjectWorkspaceSidebarProject
  backendStatus: BackendStatus
  backToDashboard: () => void
  rightPanel?: ReactNode
  renderSettingsLayer: (open: boolean) => ReactNode
  children: (state: StudioShellState) => ReactNode
}) {
  const { settingsOpen, setSettingsOpen, closeSettings } = useSettingsPopover()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  function toggleSidebar() {
    closeSettings()
    setSidebarCollapsed((value) => !value)
  }

  return (
    <div className={`nasus-app ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <ProjectWorkspaceSidebar project={project} backToDashboard={backToDashboard} setSettingsOpen={setSettingsOpen} />

      <main className="studio-main with-right-panel">
        <StudioTermsBar backendStatus={backendStatus} />
        {children({ sidebarCollapsed, toggleSidebar, backendStatus })}
      </main>

      {rightPanel}
      {renderSettingsLayer(settingsOpen)}
    </div>
  )
}
