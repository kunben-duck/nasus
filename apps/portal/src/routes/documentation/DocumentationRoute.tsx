import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { DocumentationContent } from './DocumentationContent'
import { useDocumentationRouteModel } from './useDocumentationRouteModel'

export function DocumentationRoute() {
  const model = useDocumentationRouteModel()

  return (
    <TopLevelStudioShell active="documentation" statusDependencies={model.statusDependencies}>
      {({ sidebarCollapsed, toggleSidebar }) => (
        <>
          <DocumentationContent entries={model.entries} />
          <button
            className="collapse-button dashboard-collapse-button"
            aria-expanded={!sidebarCollapsed}
            aria-label={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'}
            onClick={toggleSidebar}
            type="button"
          >
            <span className="material-symbols-outlined" aria-hidden="true">{sidebarCollapsed ? 'menu' : 'menu_open'}</span>
          </button>
        </>
      )}
    </TopLevelStudioShell>
  )
}
