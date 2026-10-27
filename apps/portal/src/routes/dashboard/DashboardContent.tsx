import type { ProjectCard } from '../../domains/platform/types'
import { MetricCard } from '../../shared/ui/MetricCard'
import { ProjectGallery } from '../../shared/ui/ProjectGallery'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function DashboardContent({
  projects,
  openProject,
}: {
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
}) {
  const { t } = useI18n()
  return (
    <section className="top-level-grid">
      <div className="page-heading compact">
        <span className="eyebrow">{t('Dashboard')}</span>
        <h1>{t('Global quality cockpit')}</h1>
        <p>{t('Ask about progress, risk, system image freshness, or release readiness across all projects.')}</p>
      </div>
      <div className="metric-grid">
        <MetricCard label={t('Active projects')} value={projects.length.toString()} />
        <MetricCard label={t('Blocked items')} value={projects.reduce((sum, item) => sum + item.blocked_items, 0).toString()} />
        <MetricCard label={t('Approvals')} value={projects.reduce((sum, item) => sum + item.pending_approvals, 0).toString()} />
      </div>
      <ProjectGallery projects={projects} openProject={openProject} />
    </section>
  )
}
