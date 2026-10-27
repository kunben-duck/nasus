import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { DashboardContent } from './DashboardContent'
import { useDashboardRouteModel } from './useDashboardRouteModel'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function DashboardRoute() {
  const model = useDashboardRouteModel()
  const { t } = useI18n()

  return (
    <TopLevelStudioShell active="dashboard" statusDependencies={model.statusDependencies}>
      {({ sidebarCollapsed, toggleSidebar }) => (
        <>
          <DashboardContent projects={model.projects} openProject={model.openProject} />
          <button
            className="collapse-button dashboard-collapse-button"
            aria-expanded={!sidebarCollapsed}
            aria-label={sidebarCollapsed ? t('Expand navigation') : t('Collapse navigation')}
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
