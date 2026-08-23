import type { ReactNode } from 'react'

import type { ProjectCard } from '../../domains/platform/types'
import type { StatusDependency } from '../../domains/platform/useStudioSettings'
import { useStudioSettings } from '../../domains/platform/useStudioSettings'
import { StudioSettingsLayer } from './StudioSettingsLayer'
import type { StudioShellState } from './StudioShellTypes'
import { ProjectWorkspaceShellView } from './ProjectWorkspaceShellView'

export function ProjectWorkspaceShell({
  project,
  statusDependencies = [],
  backToDashboard,
  rightPanel,
  children,
}: {
  project?: ProjectCard
  statusDependencies?: StatusDependency[]
  backToDashboard: () => void
  rightPanel?: ReactNode
  children: (state: StudioShellState) => ReactNode
}) {
  const studioSettings = useStudioSettings(statusDependencies)

  return (
    <ProjectWorkspaceShellView
      project={project}
      backendStatus={studioSettings.backendStatus}
      backToDashboard={backToDashboard}
      rightPanel={rightPanel}
      renderSettingsLayer={(open) => (
        <StudioSettingsLayer
          open={open}
          settings={studioSettings}
          projectId={project?.id}
          projectName={project?.name}
        />
      )}
    >
      {children}
    </ProjectWorkspaceShellView>
  )
}
