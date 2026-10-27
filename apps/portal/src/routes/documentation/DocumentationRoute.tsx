import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { DocumentationContent } from './DocumentationContent'
import { useDocumentationRouteModel } from './useDocumentationRouteModel'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function DocumentationRoute() {
  const model = useDocumentationRouteModel()
  const { t } = useI18n()

  return (
    <TopLevelStudioShell active="documentation" statusDependencies={model.statusDependencies}>
      {({ sidebarCollapsed, toggleSidebar }) => (
        <>
          <DocumentationContent entries={model.entries} />
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
