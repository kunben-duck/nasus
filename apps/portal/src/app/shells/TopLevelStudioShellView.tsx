import { useState } from 'react'
import type { ReactNode } from 'react'

import type { BackendStatus } from '../../shared/status/backendStatus'
import { StudioTermsBar } from './StudioTermsBar'
import type { StudioShellState } from './StudioShellTypes'
import { TopLevelSidebar } from './TopLevelSidebar'
import type { TopLevelNavKey } from './TopLevelSidebar'
import { useSettingsPopover } from './useSettingsPopover'

export function TopLevelStudioShellView({
  active,
  backendStatus,
  accountMenu,
  onNavigate,
  renderSettingsLayer,
  children,
}: {
  active: TopLevelNavKey
  backendStatus: BackendStatus
  accountMenu: ReactNode
  onNavigate: (path: string) => void
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
      <TopLevelSidebar
        active={active}
        setSettingsOpen={setSettingsOpen}
        accountMenu={accountMenu}
        onNavigate={onNavigate}
      />

      <main className="studio-main">
        <StudioTermsBar backendStatus={backendStatus} />
        {children({ sidebarCollapsed, toggleSidebar, backendStatus })}
      </main>

      {renderSettingsLayer(settingsOpen)}
    </div>
  )
}
