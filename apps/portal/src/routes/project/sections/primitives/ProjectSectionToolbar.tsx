export function ProjectSectionToolbar({
  title,
  sidebarCollapsed,
  toggleSidebar,
}: {
  title: string
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}) {
  return (
    <div className="workspace-toolbar">
      <button
        className="collapse-button"
        aria-expanded={!sidebarCollapsed}
        aria-label={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'}
        onClick={toggleSidebar}
        type="button"
      >
        <span className="material-symbols-outlined" aria-hidden="true">
          {sidebarCollapsed ? 'menu' : 'menu_open'}
        </span>
      </button>
      <strong>{title}</strong>
      <div className="toolbar-actions">
        <button>Share</button>
        <button>＋</button>
        <button>⋮</button>
      </div>
    </div>
  )
}
