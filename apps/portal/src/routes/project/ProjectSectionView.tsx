import { ProjectSectionToolbar } from './sections/primitives/ProjectSectionToolbar'
import { renderProjectSection, titleForProjectSection } from './ProjectSectionRegistry'
import type { ProjectSection, ProjectSectionParams } from './ProjectSectionRegistry'
import type { ProjectRouteContext, ProjectRouteShellState } from './ProjectRouteTypes'
import { useI18n } from '../../shared/i18n/I18nProvider'

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
  const { tx } = useI18n()
  return (
    <section className={`agent-workspace project-section-route${section === 'knowledge' ? ' knowledge-workspace' : ''}`} data-testid={`project-${section}-route`}>
      <ProjectSectionToolbar
        title={tx(titleForProjectSection(section))}
        sidebarCollapsed={shellState.sidebarCollapsed}
        toggleSidebar={shellState.toggleSidebar}
      />
      {renderProjectSection(section, context, params)}
    </section>
  )
}
