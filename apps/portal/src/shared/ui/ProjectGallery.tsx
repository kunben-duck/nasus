import { useI18n } from '../i18n/I18nProvider'

export type ProjectGalleryItem = {
  id: string
  code: string
  risk: string
  name: string
  summary: string
  progress: number
  active_version: string
  preview_only?: boolean
}

export function ProjectGallery<TProject extends ProjectGalleryItem>({
  projects,
  openProject,
  limit = 8,
}: {
  projects: TProject[]
  openProject: (project: TProject) => void
  limit?: number
}) {
  const { t, tx } = useI18n()
  const visibleProjects = projects.slice(0, limit)
  const hiddenProjectCount = Math.max(0, projects.length - visibleProjects.length)

  return (
    <div className="project-gallery">
      {visibleProjects.map((project) => (
        <button
          aria-label={project.preview_only ? t('Use {name} starting point', { name: tx(project.name) }) : undefined}
          className="project-card-ai"
          data-project-kind={project.preview_only ? 'starting-point' : 'project'}
          data-testid="project-card"
          key={project.id}
          onClick={() => openProject(project)}
        >
          <div className="project-card-top">
            <span className="project-code">{project.code}</span>
            <span className={`risk-pill ${project.risk}`}>{tx(project.risk)}</span>
          </div>
          <strong>{tx(project.name)}</strong>
          <p>{tx(project.summary)}</p>
          <div className="progress-track"><span style={{ width: `${project.progress}%` }} /></div>
          <div className="project-meta">
            <span>{tx(project.active_version)}</span>
            <span>{project.progress}%</span>
          </div>
        </button>
      ))}
      {hiddenProjectCount > 0 ? (
        <div className="project-card-ai project-card-more" aria-label={t('{count} more projects', { count: hiddenProjectCount })}>
          <div className="project-card-top">
            <span className="project-code">{t('ALL')}</span>
            <span className="risk-pill low">{hiddenProjectCount}</span>
          </div>
          <strong>{t('More projects are indexed')}</strong>
          <p>{t('Ask Nasus in Dashboard to filter by risk, owner, version, or release readiness.')}</p>
          <div className="project-meta">
            <span>{t('Dashboard query')}</span>
            <span>{t('Agent first')}</span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
