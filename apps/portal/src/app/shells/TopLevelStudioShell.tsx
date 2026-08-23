import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import type { StatusDependency } from '../../domains/platform/useStudioSettings'
import { useStudioSettings } from '../../domains/platform/useStudioSettings'
import { StudioSettingsLayer } from './StudioSettingsLayer'
import type { StudioShellState } from './StudioShellTypes'
import type { TopLevelNavKey } from './TopLevelSidebar'
import { TopLevelStudioShellView } from './TopLevelStudioShellView'
import { UserAccountMenuContainer } from './UserAccountMenuContainer'

export function TopLevelStudioShell({
  active,
  statusDependencies = [],
  children,
}: {
  active: TopLevelNavKey
  statusDependencies?: StatusDependency[]
  children: (state: StudioShellState) => ReactNode
}) {
  const studioSettings = useStudioSettings(statusDependencies)
  const navigate = useNavigate()

  return (
    <TopLevelStudioShellView
      active={active}
      backendStatus={studioSettings.backendStatus}
      accountMenu={<UserAccountMenuContainer />}
      onNavigate={(path) => navigate(path)}
      renderSettingsLayer={(open) => <StudioSettingsLayer open={open} settings={studioSettings} />}
    >
      {children}
    </TopLevelStudioShellView>
  )
}
