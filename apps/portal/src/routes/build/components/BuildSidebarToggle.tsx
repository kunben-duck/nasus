import { useI18n } from '../../../shared/i18n/I18nProvider'

export function BuildSidebarToggle({
  sidebarCollapsed,
  toggleSidebar,
}: {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}) {
  const { t } = useI18n()
  return (
    <button
      className="collapse-button"
      aria-expanded={!sidebarCollapsed}
      aria-label={sidebarCollapsed ? t('Expand navigation') : t('Collapse navigation')}
      onClick={toggleSidebar}
      type="button"
    >
      <span className="material-symbols-outlined" aria-hidden="true">
        {sidebarCollapsed ? 'menu' : 'menu_open'}
      </span>
    </button>
  )
}
