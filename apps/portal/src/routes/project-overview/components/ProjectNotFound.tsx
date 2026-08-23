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
  return (
    <section className="agent-workspace project-not-found" data-testid="project-not-found">
      <div className="workspace-toolbar">
        <button
          className="collapse-button"
          aria-expanded={!sidebarCollapsed}
          aria-label={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'}
          onClick={toggleSidebar}
          type="button"
        >
          <span className="material-symbols-outlined" aria-hidden="true">{sidebarCollapsed ? 'menu' : 'menu_open'}</span>
        </button>
        <strong>Project not found</strong>
      </div>
      <div className="empty-state-card">
        <span className="eyebrow">Project route</span>
        <h1>{loading ? 'Loading project context' : 'This project is not available'}</h1>
        <p>
          {loading
            ? 'Nasus is loading the project catalog before enabling project-scoped agent actions.'
            : `No project matches "${projectId ?? 'unknown'}". Project-scoped tools are disabled so the agent cannot accidentally operate on another project.`}
        </p>
        <button className="composer-action-button build-submit-button" onClick={backToDashboard} type="button">
          Back to Dashboard
        </button>
      </div>
    </section>
  )
}
