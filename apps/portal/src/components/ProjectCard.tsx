import { Link } from 'react-router-dom'

import type { ProjectCard as ProjectCardType } from '../features/types'

export function ProjectCard({ project }: { project: ProjectCardType }) {
  return (
    <article className="project-card">
      <div className="project-card-header">
        <div>
          <p className="eyebrow">{project.code}</p>
          <h3>{project.name}</h3>
        </div>
        <span className={`status-badge ${project.risk}`}>{project.risk} risk</span>
      </div>
      <p className="surface-description">{project.summary}</p>
      <div className="project-metrics">
        <div>
          <strong>{project.progress}%</strong>
          <span>progress</span>
        </div>
        <div>
          <strong>{project.blocked_items}</strong>
          <span>blocked</span>
        </div>
        <div>
          <strong>{project.pending_approvals}</strong>
          <span>approvals</span>
        </div>
      </div>
      <div className="card-actions">
        <Link className="ghost-button" data-action="open_project" data-project={project.id} to={`/projects/${project.id}`}>
          Open Project
        </Link>
      </div>
    </article>
  )
}
