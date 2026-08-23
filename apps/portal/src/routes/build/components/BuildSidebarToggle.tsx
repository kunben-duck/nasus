export function BuildSidebarToggle({
  sidebarCollapsed,
  toggleSidebar,
}: {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}) {
  return (
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
  )
}
