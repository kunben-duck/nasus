import type { ReactNode } from 'react'

type SidebarIconName = 'notifications' | 'settings' | 'search' | 'key'
export type TopLevelNavKey = 'build' | 'dashboard' | 'documentation'

function SidebarIcon({ name }: { name: SidebarIconName }) {
  return <span className="material-symbols-outlined" aria-hidden="true">{name}</span>
}

function SectionLabel({ label }: { label: string }) {
  return <div className="section-label">{label}</div>
}

function NavButton({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean
  label: string
  icon: string
  onClick: () => void
}) {
  return (
    <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick}>
      <span>{icon}</span>
      <span>{label}</span>
      {label === 'Dashboard' ? <span className="nav-chevron">›</span> : null}
    </button>
  )
}

export function TopLevelSidebar({
  active,
  accountMenu,
  setSettingsOpen,
  onNavigate,
}: {
  active: TopLevelNavKey
  accountMenu: ReactNode
  setSettingsOpen: (value: boolean | ((value: boolean) => boolean)) => void
  onNavigate: (path: string) => void
}) {
  return (
    <aside className="studio-sidebar">
      <div className="brand-row">
        <img className="brand-mark" src="/nasus.png" alt="Nasus" />
        <div>
          <div className="brand-name">Nasus Studio</div>
        </div>
      </div>

      <nav className="nav-stack">
        <SectionLabel label="Explore" />
        <NavButton active={active === 'build'} label="Build" icon="+" onClick={() => onNavigate('/build')} />
        <NavButton active={active === 'dashboard'} label="Dashboard" icon="◔" onClick={() => onNavigate('/dashboard')} />
        <SectionLabel label="Quality" />
        <NavButton active={false} label="System image" icon="▦" onClick={() => onNavigate('/dashboard')} />
        <NavButton active={false} label="Quality loops" icon="⌁" onClick={() => onNavigate('/dashboard')} />
        <NavButton active={false} label="Runs" icon="▻" onClick={() => onNavigate('/dashboard')} />
        <SectionLabel label="Manage" />
        <NavButton
          active={active === 'documentation'}
          label="Documentation"
          icon="□"
          onClick={() => onNavigate('/documentation')}
        />
      </nav>

      <div className="sidebar-spacer" />
      <div className="upgrade-card">
        <strong>Agent autonomy</strong>
        <span>All product actions are tools. Chat and buttons share the same command surface.</span>
      </div>
      <div className="sidebar-actions">
        <button className="icon-tile" aria-label="Notifications">
          <SidebarIcon name="notifications" />
        </button>
        <button
          className="icon-tile"
          aria-label="Settings"
          data-settings-toggle
          onClick={() => setSettingsOpen((value) => !value)}
        >
          <SidebarIcon name="settings" />
        </button>
        <button className="icon-tile" aria-label="Search">
          <SidebarIcon name="search" />
        </button>
        <button className="icon-tile" aria-label="API key">
          <SidebarIcon name="key" />
        </button>
      </div>
      {accountMenu}
    </aside>
  )
}
