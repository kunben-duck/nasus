import { useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren, ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

type ShellMode = 'global' | 'project'

export interface InspectorTab {
  id: string
  label: string
  content: ReactNode
}

export interface InspectorRailConfig {
  title: string
  tabs: InspectorTab[]
  defaultTabId?: string
}

const globalNav = [
  { label: 'Welcome', href: '/welcome' },
  { label: 'Build', href: '/build' },
  { label: 'Dashboard', href: '/dashboard' },
  { label: 'Documentation', href: '/documentation' },
]

function projectNav(projectId?: string) {
  if (!projectId) return []
  return [
    { label: 'Project Overview', href: `/projects/${projectId}` },
    { label: 'Version Space', href: `/projects/${projectId}/versions` },
    { label: 'Personal Workspace', href: `/projects/${projectId}/workspaces/us_123` },
    { label: 'Knowledge', href: `/projects/${projectId}/knowledge` },
    { label: 'Runs', href: `/projects/${projectId}/runs` },
    { label: 'Governance', href: `/projects/${projectId}/governance` },
  ]
}

export function WorkspaceShell({
  mode,
  projectId,
  inspector,
  backHref,
  backLabel,
  children,
}: PropsWithChildren<{
  mode: ShellMode
  projectId?: string
  inspector: InspectorRailConfig
  backHref?: string
  backLabel?: string
}>) {
  const location = useLocation()
  const navItems = mode === 'global' ? globalNav : projectNav(projectId)
  const isActive = (href: string) => location.pathname === href || location.pathname.startsWith(`${href}/`)
  const tabIds = useMemo(() => inspector.tabs.map((tab) => tab.id).join('|'), [inspector.tabs])
  const [activeTabId, setActiveTabId] = useState(inspector.defaultTabId ?? inspector.tabs[0]?.id ?? '')

  useEffect(() => {
    setActiveTabId(inspector.defaultTabId ?? inspector.tabs[0]?.id ?? '')
  }, [inspector.defaultTabId, location.pathname, tabIds])

  const activeTab = inspector.tabs.find((tab) => tab.id === activeTabId) ?? inspector.tabs[0]

  return (
    <div className="app-shell">
      <aside className="left-rail">
        <div className="brand-block">
          <div className="brand-mark">N</div>
          <div>
            <div className="brand-title">Nasus</div>
            <div className="brand-subtitle">{mode === 'global' ? 'Agent-first quality studio' : 'Project space'}</div>
          </div>
        </div>
        {mode === 'project' ? (
          <Link className="back-link" to={backHref ?? '/dashboard'}>
            ← {backLabel ?? 'Dashboard'}
          </Link>
        ) : null}
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link
              className={`nav-item ${isActive(item.href) ? 'active' : ''}`}
              key={item.href}
              to={item.href}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="main-stage">{children}</main>
      <aside className="right-rail">
        <div className="panel-header">
          <h2>{inspector.title}</h2>
          <button type="button">Inspect</button>
        </div>
        {inspector.tabs.length > 0 ? (
          <>
            <div className="panel-tabs">
              <div className="panel-tab-group">
                {inspector.tabs.map((tab) => (
                  <button
                    className={`panel-tab ${tab.id === activeTab?.id ? 'active' : ''}`}
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTabId(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="panel-content custom-scrollbar">{activeTab?.content}</div>
          </>
        ) : null}
      </aside>
    </div>
  )
}

export function Surface({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="surface">
      <header className="surface-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>{title}</h1>
          <p className="surface-description">{description}</p>
        </div>
        {actions ? <div className="surface-actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  )
}
