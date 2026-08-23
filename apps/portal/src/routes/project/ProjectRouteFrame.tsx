import type { ReactNode } from 'react'

import { ProjectWorkspaceShell } from '../../app/shells/ProjectWorkspaceShell'
import { ProjectNotFound } from '../project-overview/components/ProjectNotFound'
import { RunSettingsPanel } from '../project-overview/components/RunSettingsPanel'
import type { ProjectRouteContext, ProjectRouteShellState } from './ProjectRouteTypes'
import { useProjectRouteContext } from './useProjectRouteContext'

export function ProjectRouteFrame({
  children,
}: {
  children: (context: ProjectRouteContext, shellState: ProjectRouteShellState) => ReactNode
}) {
  const route = useProjectRouteContext()

  return (
    <ProjectWorkspaceShell
      project={route.project}
      backToDashboard={route.backToDashboard}
      statusDependencies={[route.projectStatusDependency]}
      rightPanel={<RunSettingsPanel project={route.project} systemImage={route.systemImage} />}
    >
      {({ sidebarCollapsed, toggleSidebar }) => (
        route.context ? (
          children(route.context, { sidebarCollapsed, toggleSidebar })
        ) : (
          <ProjectNotFound
            projectId={route.projectId}
            loading={route.projectLoading}
            backToDashboard={route.backToDashboard}
            sidebarCollapsed={sidebarCollapsed}
            toggleSidebar={toggleSidebar}
          />
        )
      )}
    </ProjectWorkspaceShell>
  )
}
