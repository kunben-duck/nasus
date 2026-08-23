import type { SettingsMenuItem, SettingsPanel } from './settingsTypes'

export function SettingsMenu({
  items,
  activePanel,
  onSelect,
}: {
  items: SettingsMenuItem[]
  activePanel: SettingsPanel
  onSelect: (panel: SettingsPanel) => void
}) {
  return (
    <div className="settings-menu">
      {items.map((item) => (
        <button
          className={`${item.id === activePanel ? 'active' : ''} ${item.separator ? 'with-separator' : ''}`}
          key={item.label}
          onClick={() => item.id ? onSelect(item.id) : undefined}
          type="button"
        >
          <span className="settings-menu-icon">{item.icon}</span>
          <span className="settings-menu-label">{item.label}</span>
          {item.value ? <span className="settings-menu-value">{item.value}</span> : null}
          {item.id ? <span className="settings-menu-chevron">›</span> : null}
        </button>
      ))}
    </div>
  )
}
