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
}: {
  projects: TProject[]
  openProject: (project: TProject) => void
}) {
  const visibleProjects = projects.slice(0, 8)
  const hiddenProjectCount = Math.max(0, projects.length - visibleProjects.length)

  return (
    <div className="project-gallery">
      {visibleProjects.map((project) => (
        <button
          aria-label={project.preview_only ? `Use ${project.name} starting point` : undefined}
          className="project-card-ai"
          data-project-kind={project.preview_only ? 'starting-point' : 'project'}
          data-testid="project-card"
          key={project.id}
          onClick={() => openProject(project)}
        >
          <div className="project-card-top">
            <span className="project-code">{project.code}</span>
            <span className={`risk-pill ${project.risk}`}>{project.risk}</span>
          </div>
          <strong>{project.name}</strong>
          <p>{project.summary}</p>
          <div className="progress-track"><span style={{ width: `${project.progress}%` }} /></div>
          <div className="project-meta">
            <span>{project.active_version}</span>
            <span>{project.progress}%</span>
          </div>
        </button>
      ))}
      {hiddenProjectCount > 0 ? (
        <div className="project-card-ai project-card-more" aria-label={`${hiddenProjectCount} more projects`}>
          <div className="project-card-top">
            <span className="project-code">ALL</span>
            <span className="risk-pill low">{hiddenProjectCount}</span>
          </div>
          <strong>More projects are indexed</strong>
          <p>Ask Nasus in Dashboard to filter by risk, owner, version, or release readiness.</p>
          <div className="project-meta">
            <span>Dashboard query</span>
            <span>Agent first</span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
