import type { ProjectCard } from '../../domains/platform/types'
import { MetricCard } from '../../shared/ui/MetricCard'
import { ProjectGallery } from '../../shared/ui/ProjectGallery'

export function DashboardContent({
  projects,
  openProject,
}: {
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
}) {
  return (
    <section className="top-level-grid">
      <div className="page-heading compact">
        <span className="eyebrow">Dashboard</span>
        <h1>Global quality cockpit</h1>
        <p>Ask about progress, risk, system image freshness, or release readiness across all projects.</p>
      </div>
      <div className="metric-grid">
        <MetricCard label="Active projects" value={projects.length.toString()} />
        <MetricCard label="Blocked items" value={projects.reduce((sum, item) => sum + item.blocked_items, 0).toString()} />
        <MetricCard label="Approvals" value={projects.reduce((sum, item) => sum + item.pending_approvals, 0).toString()} />
      </div>
      <ProjectGallery projects={projects} openProject={openProject} />
    </section>
  )
}
