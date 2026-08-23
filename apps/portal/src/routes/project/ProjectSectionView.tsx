import { ProjectSectionToolbar } from './sections/primitives/ProjectSectionToolbar'
import { renderProjectSection, titleForProjectSection } from './ProjectSectionRegistry'
import type { ProjectSection, ProjectSectionParams } from './ProjectSectionRegistry'
import type { ProjectRouteContext, ProjectRouteShellState } from './ProjectRouteTypes'

export function ProjectSectionView({
  section,
  context,
  shellState,
  params,
}: {
  section: ProjectSection
  context: ProjectRouteContext
  shellState: ProjectRouteShellState
  params: ProjectSectionParams
}) {
  return (
    <section className="agent-workspace project-section-route" data-testid={`project-${section}-route`}>
      <ProjectSectionToolbar
        title={titleForProjectSection(section)}
        sidebarCollapsed={shellState.sidebarCollapsed}
        toggleSidebar={shellState.toggleSidebar}
      />
      {renderProjectSection(section, context, params)}
    </section>
  )
}
