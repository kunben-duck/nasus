import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { DashboardContent } from './DashboardContent'
import { useDashboardRouteModel } from './useDashboardRouteModel'

export function DashboardRoute() {
  const model = useDashboardRouteModel()

  return (
    <TopLevelStudioShell active="dashboard" statusDependencies={model.statusDependencies}>
      {({ sidebarCollapsed, toggleSidebar }) => (
        <>
          <DashboardContent projects={model.projects} openProject={model.openProject} />
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
