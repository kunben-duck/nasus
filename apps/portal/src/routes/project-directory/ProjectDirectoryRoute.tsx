import { useNavigate } from 'react-router-dom'

import { TopLevelStudioShell } from '../../app/shells/TopLevelStudioShell'
import { projectFeatureNavigation, projectNavigationPath } from '../../app/routing/studioNavigation'
import type { ProjectFeatureKey } from '../../app/routing/studioNavigation'
import { useProjectDirectory } from '../../domains/platform/useProjectDirectory'
import { useI18n } from '../../shared/i18n/I18nProvider'
import { ProjectDirectoryContent } from './ProjectDirectoryContent'

export function ProjectDirectoryRoute({ feature }: { feature: ProjectFeatureKey }) {
  const directory = useProjectDirectory()
  const navigate = useNavigate()
  const { t } = useI18n()
  return (
    <TopLevelStudioShell active={feature} statusDependencies={directory.statusDependencies}>
      {({ sidebarCollapsed, toggleSidebar }) => (
        <>
          <ProjectDirectoryContent
            title={projectFeatureNavigation[feature].label}
            description={projectFeatureNavigation[feature].description}
            projects={directory.projects}
            loading={directory.loading}
            error={directory.error}
            reload={() => { void directory.reload() }}
            createProject={() => navigate('/build')}
            openProject={(project) => navigate(projectNavigationPath(project.id, feature))}
          />
          <button className="collapse-button dashboard-collapse-button" type="button"
            aria-expanded={!sidebarCollapsed}
            aria-label={sidebarCollapsed ? t('Expand navigation') : t('Collapse navigation')}
            onClick={toggleSidebar}>
            <span className="material-symbols-outlined" aria-hidden="true">{sidebarCollapsed ? 'menu' : 'menu_open'}</span>
          </button>
        </>
      )}
    </TopLevelStudioShell>
  )
}
