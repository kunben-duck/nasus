import type { ReactNode } from 'react'

import { useI18n } from '../../shared/i18n/I18nProvider'
import { projectFeatureNavigation } from '../routing/studioNavigation'
import type { TopLevelNavKey } from '../routing/studioNavigation'

type SidebarIconName = 'notifications' | 'settings' | 'search' | 'key'
export type { TopLevelNavKey } from '../routing/studioNavigation'

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
    <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick} type="button"
      aria-label={label} title={label} aria-current={active ? 'page' : undefined}>
      <span aria-hidden="true">{icon}</span>
      <span>{label}</span>
      {icon === '◔' ? <span className="nav-chevron">›</span> : null}
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
  const { t } = useI18n()
  function navigateTo(path: string) {
    setSettingsOpen(false)
    onNavigate(path)
  }

  return (
    <aside className="studio-sidebar">
      <div className="brand-row">
        <img className="brand-mark" src="/nasus.png" alt="Nasus" />
        <div>
          <div className="brand-name">Nasus Studio</div>
        </div>
      </div>

      <nav className="nav-stack">
        <SectionLabel label={t('Explore')} />
        <NavButton active={active === 'build'} label={t('Build')} icon="+" onClick={() => navigateTo('/build')} />
        <NavButton active={active === 'dashboard'} label={t('Dashboard')} icon="◔" onClick={() => navigateTo('/dashboard')} />
        <SectionLabel label={t('Quality')} />
        <NavButton active={active === 'system-image'} label={t('System image')} icon="▦" onClick={() => navigateTo(projectFeatureNavigation['system-image'].path)} />
        <NavButton active={active === 'quality-loops'} label={t('Quality loops')} icon="⌁" onClick={() => navigateTo(projectFeatureNavigation['quality-loops'].path)} />
        <NavButton active={active === 'runs'} label={t('Runs')} icon="▻" onClick={() => navigateTo(projectFeatureNavigation.runs.path)} />
        <SectionLabel label={t('Manage')} />
        <NavButton
          active={active === 'documentation'}
          label={t('Documentation')}
          icon="□"
          onClick={() => navigateTo('/documentation')}
        />
      </nav>

      <div className="sidebar-spacer" />
      <div className="upgrade-card">
        <strong>{t('Agent autonomy')}</strong>
        <span>{t('All product actions are tools. Chat and buttons share the same command surface.')}</span>
      </div>
      <div className="sidebar-actions">
        <button className="icon-tile" aria-label={t('Notifications')}>
          <SidebarIcon name="notifications" />
        </button>
        <button
          className="icon-tile"
          aria-label={t('Settings')}
          data-settings-toggle
          onClick={() => setSettingsOpen((value) => !value)}
        >
          <SidebarIcon name="settings" />
        </button>
        <button className="icon-tile" aria-label={t('Search')}>
          <SidebarIcon name="search" />
        </button>
        <button className="icon-tile" aria-label={t('API key')}>
          <SidebarIcon name="key" />
        </button>
      </div>
      {accountMenu}
    </aside>
  )
}
