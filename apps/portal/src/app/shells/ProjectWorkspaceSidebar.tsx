import type { Dispatch, SetStateAction } from 'react'

import type { ProjectCard } from '../../domains/platform/types'
import { StudioSidebarIcon } from '../../shared/ui/StudioSidebarIcon'
import { UserAccountMenuContainer } from './UserAccountMenuContainer'

export function ProjectWorkspaceSidebar({
  project,
  backToDashboard,
  setSettingsOpen,
}: {
  project?: ProjectCard
  backToDashboard: () => void
  setSettingsOpen: Dispatch<SetStateAction<boolean>>
}) {
  return (
    <aside className="studio-sidebar">
      <div className="brand-row">
        <img className="brand-mark" src="/nasus.png" alt="Nasus" />
        <div>
          <div className="brand-name">Nasus Studio</div>
        </div>
        <button className="round-icon subtle" onClick={backToDashboard} aria-label="Back to dashboard" type="button">
          ←
        </button>
      </div>

      <ProjectNav project={project} />

      <div className="sidebar-spacer" />
      <div className="upgrade-card">
        <strong>Agent autonomy</strong>
        <span>All product actions are tools. Chat and buttons share the same command surface.</span>
      </div>
      <div className="sidebar-actions">
        <button className="icon-tile" aria-label="Notifications"><StudioSidebarIcon name="notifications" /></button>
        <button className="icon-tile" aria-label="Settings" data-settings-toggle onClick={() => setSettingsOpen((value) => !value)}>
          <StudioSidebarIcon name="settings" />
        </button>
        <button className="icon-tile" aria-label="Search"><StudioSidebarIcon name="search" /></button>
        <button className="icon-tile" aria-label="API key"><StudioSidebarIcon name="key" /></button>
      </div>
      <UserAccountMenuContainer />
    </aside>
  )
}

function ProjectNav({ project }: { project?: ProjectCard }) {
  return (
    <nav className="nav-stack">
      <SectionLabel label={project?.code ?? 'Project'} />
      <div className="project-mini">
        <strong>{project?.name ?? 'Project Space'}</strong>
        <span>{project?.active_version ?? 'No version'} · {project?.progress ?? 0}% closed</span>
      </div>
      <NavButton active label="Agent workspace" icon="✦" />
      <NavButton active={false} label="System image" icon="▦" />
      <NavButton active={false} label="Quality loop" icon="⌁" />
      <NavButton active={false} label="Runs" icon="▻" />
      <NavButton active={false} label="Governance" icon="◇" />
    </nav>
  )
}

function SectionLabel({ label }: { label: string }) {
  return <div className="section-label">{label}</div>
}

function NavButton({ active, label, icon }: { active: boolean; label: string; icon: string }) {
  return (
    <button className={`nav-button ${active ? 'active' : ''}`} type="button">
      <span>{icon}</span>
      <span>{label}</span>
    </button>
  )
}
