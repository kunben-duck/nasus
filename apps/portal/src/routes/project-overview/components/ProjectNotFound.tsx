import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ProjectNotFound({
  projectId,
  loading,
  backToDashboard,
  sidebarCollapsed,
  toggleSidebar,
}: {
  projectId: string | null
  loading: boolean
  backToDashboard: () => void
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}) {
  const { t } = useI18n()
  return (
    <section className="agent-workspace project-not-found" data-testid="project-not-found">
      <div className="workspace-toolbar">
        <button
          className="collapse-button"
          aria-expanded={!sidebarCollapsed}
          aria-label={sidebarCollapsed ? t('Expand navigation') : t('Collapse navigation')}
          onClick={toggleSidebar}
          type="button"
        >
          <span className="material-symbols-outlined" aria-hidden="true">{sidebarCollapsed ? 'menu' : 'menu_open'}</span>
        </button>
        <strong>{t('Project not found')}</strong>
      </div>
      <div className="empty-state-card">
        <span className="eyebrow">{t('Project route')}</span>
        <h1>{loading ? t('Loading project context') : t('This project is not available')}</h1>
        <p>
          {loading
            ? t('Nasus is loading the project catalog before enabling project-scoped agent actions.')
            : t('No project matches "{id}". Project-scoped tools are disabled so the agent cannot accidentally operate on another project.', { id: projectId ?? 'unknown' })}
        </p>
        <button className="composer-action-button build-submit-button" onClick={backToDashboard} type="button">
          {t('Back to Dashboard')}
        </button>
      </div>
    </section>
  )
}
