import type { ProjectCard } from '../../domains/platform/types'
import { useI18n } from '../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../shared/i18n/messages'
import { ProjectGallery } from '../../shared/ui/ProjectGallery'

export function ProjectDirectoryContent({
  title, description, projects, loading, error, reload, createProject, openProject,
}: {
  title: MessageKey
  description: MessageKey
  projects: ProjectCard[]
  loading: boolean
  error: boolean
  reload: () => void
  createProject: () => void
  openProject: (project: ProjectCard) => void
}) {
  const { t } = useI18n()
  return (
    <section className="top-level-grid" data-testid="project-directory">
      <div className="page-heading compact">
        <span className="eyebrow">{t('Choose a project')}</span>
        <h1>{t(title)}</h1>
        <p>{t(description)}</p>
      </div>
      {error ? (
        <div role="alert">
          <p>{t('Unable to load projects. Check your connection and try again.')}</p>
          <button className="composer-action-button" type="button" onClick={reload}>{t('Reload projects')}</button>
        </div>
      ) : loading ? (
        <p role="status">{t('Loading projects...')}</p>
      ) : projects.length ? (
        <ProjectGallery projects={projects} openProject={openProject} limit={projects.length} />
      ) : (
        <div role="status">
          <p>{t('No projects available. Create a project or ask an administrator to add you to one.')}</p>
          <button className="composer-action-button" type="button" onClick={createProject}>{t('Create a project')}</button>
        </div>
      )}
    </section>
  )
}
