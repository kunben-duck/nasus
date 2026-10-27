import type { ProjectCard } from '../../../domains/platform/types'
import { ProjectGallery } from '../../../shared/ui/ProjectGallery'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function BuildGalleryPanel({
  projects,
  openProject,
}: {
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
}) {
  const { t } = useI18n()
  return (
    <div className="gallery-panel">
      <div className="gallery-header">
        <h2>{t('Discover project starting points')}</h2>
        <button>{t('Browse templates')} →</button>
      </div>
      <ProjectGallery projects={projects} openProject={openProject} />
    </div>
  )
}
