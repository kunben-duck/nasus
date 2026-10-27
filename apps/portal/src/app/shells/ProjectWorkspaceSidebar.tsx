import type { Dispatch, SetStateAction } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import type { ProjectCard } from '../../domains/platform/types'
import { StudioSidebarIcon } from '../../shared/ui/StudioSidebarIcon'
import { UserAccountMenuContainer } from './UserAccountMenuContainer'
import { useI18n } from '../../shared/i18n/I18nProvider'
import { activeProjectNavKey, projectNavigationPath } from '../routing/studioNavigation'
import type { ProjectNavKey } from '../routing/studioNavigation'

export function ProjectWorkspaceSidebar({
  project,
  backToDashboard,
  setSettingsOpen,
}: {
  project?: ProjectCard
  backToDashboard: () => void
  setSettingsOpen: Dispatch<SetStateAction<boolean>>
}) {
  const { t } = useI18n()
  return (
    <aside className="studio-sidebar">
      <div className="brand-row">
        <img className="brand-mark" src="/nasus.png" alt="Nasus" />
        <div>
          <div className="brand-name">Nasus Studio</div>
        </div>
        <button className="round-icon subtle" onClick={backToDashboard} aria-label={t('Back to dashboard')} type="button">
          ←
        </button>
      </div>

      <ProjectNav project={project} />

      <div className="sidebar-spacer" />
      <div className="upgrade-card">
        <strong>{t('Agent autonomy')}</strong>
        <span>{t('All product actions are tools. Chat and buttons share the same command surface.')}</span>
      </div>
      <div className="sidebar-actions">
        <button className="icon-tile" aria-label={t('Notifications')}><StudioSidebarIcon name="notifications" /></button>
        <button className="icon-tile" aria-label={t('Settings')} data-settings-toggle onClick={() => setSettingsOpen((value) => !value)}>
          <StudioSidebarIcon name="settings" />
        </button>
        <button className="icon-tile" aria-label={t('Search')}><StudioSidebarIcon name="search" /></button>
        <button className="icon-tile" aria-label={t('API key')}><StudioSidebarIcon name="key" /></button>
      </div>
      <UserAccountMenuContainer />
    </aside>
  )
}

function ProjectNav({ project }: { project?: ProjectCard }) {
  const { t } = useI18n()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const active = activeProjectNavKey(pathname)
  function openSection(key: ProjectNavKey) {
    if (project) navigate(projectNavigationPath(project.id, key))
  }
  return (
    <nav className="nav-stack">
      <SectionLabel label={project?.code ?? t('Project')} />
      <div className="project-mini">
        <strong>{project?.name ?? t('Project Space')}</strong>
        <span>{project?.active_version ?? t('No version')} · {t('{progress}% closed', { progress: project?.progress ?? 0 })}</span>
      </div>
      <NavButton active={active === 'agent-workspace'} disabled={!project} label={t('Agent workspace')} icon="✦" onClick={() => openSection('agent-workspace')} />
      <NavButton active={active === 'system-image'} disabled={!project} label={t('System image')} icon="▦" onClick={() => openSection('system-image')} />
      <NavButton active={active === 'quality-loops'} disabled={!project} label={t('Quality loop')} icon="⌁" onClick={() => openSection('quality-loops')} />
      <NavButton active={active === 'runs'} disabled={!project} label={t('Runs')} icon="▻" onClick={() => openSection('runs')} />
      <NavButton active={active === 'governance'} disabled={!project} label={t('Governance')} icon="◇" onClick={() => openSection('governance')} />
      <NavButton active={active === 'release-readiness'} disabled={!project} label={t('Release Readiness')} icon="◎" onClick={() => openSection('release-readiness')} />
    </nav>
  )
}

function SectionLabel({ label }: { label: string }) {
  return <div className="section-label">{label}</div>
}

function NavButton({ active, disabled, label, icon, onClick }: {
  active: boolean
  disabled: boolean
  label: string
  icon: string
  onClick: () => void
}) {
  return (
    <button className={`nav-button ${active ? 'active' : ''}`} type="button" disabled={disabled} onClick={onClick}
      aria-label={label} title={label} aria-current={active ? 'page' : undefined}>
      <span aria-hidden="true">{icon}</span>
      <span>{label}</span>
    </button>
  )
}
