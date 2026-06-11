import type { ReactNode } from 'react'

import type {
  BuildData,
  DashboardData,
  DocumentationEntry,
  KnowledgeObject,
  ProjectWorkspaceData,
  ReleaseReadiness,
  WelcomeData,
  WorkspaceData,
} from '../features/types'
import type { InspectorRailConfig } from '../components/WorkspaceShell'

function renderTextList(items: ReactNode[]) {
  return (
    <ul className="simple-list inspector-list">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

function card(title: string, body: ReactNode) {
  return (
    <section className="inspector-card">
      <h3>{title}</h3>
      {body}
    </section>
  )
}

export function welcomeInspectorRail(data?: WelcomeData): InspectorRailConfig {
  return {
    title: 'Studio Overview',
    defaultTabId: 'activity',
    tabs: [
      {
        id: 'activity',
        label: 'Activity',
        content: (
          <div className="inspector-stack">
            {card('Recent projects', renderTextList((data?.recent_projects ?? []).map((project) => `${project.name} · ${project.progress}% progress`)))}
            {card('Recent conversations', renderTextList((data?.recent_conversations ?? []).map((session) => session.title)))}
          </div>
        ),
      },
      {
        id: 'tips',
        label: 'Tips',
        content: (
          <div className="inspector-stack">
            {card('Suggested starts', renderTextList([
              'Create a new project and connect Git + US inputs.',
              'Resume an active release branch from the dashboard.',
              'Open a US workspace and continue the quality closure loop.',
            ]))}
          </div>
        ),
      },
      {
        id: 'status',
        label: 'Status',
        content: (
          <div className="inspector-stack">
            {card('Platform status', renderTextList([
              `${data?.recent_projects.length ?? 0} projects available`,
              `${data?.recent_versions.length ?? 0} recent versions tracked`,
              `${data?.recent_conversations.length ?? 0} resumable conversations`,
            ]))}
          </div>
        ),
      },
    ],
  }
}

export function buildInspectorRail(data?: BuildData): InspectorRailConfig {
  return {
    title: 'Build Context',
    defaultTabId: 'projects',
    tabs: [
      {
        id: 'projects',
        label: 'Projects',
        content: (
          <div className="inspector-stack">
            {card('Draft setups', renderTextList((data?.drafts ?? []).map((project) => `${project.name} · ${project.system_image_status}`)))}
          </div>
        ),
      },
      {
        id: 'imports',
        label: 'Imports',
        content: (
          <div className="inspector-stack">
            {card('Import readiness', renderTextList(data?.imports_health ?? ['No import checks yet']))}
          </div>
        ),
      },
      {
        id: 'health',
        label: 'Health',
        content: (
          <div className="inspector-stack">
            {card('Provider health', <p>{data?.provider_health ?? 'Checking provider health'}</p>)}
          </div>
        ),
      },
    ],
  }
}

export function dashboardInspectorRail(data?: DashboardData): InspectorRailConfig {
  const riskyProjects = (data?.projects ?? []).filter((project) => project.risk === 'high' || project.blocked_items > 0)
  return {
    title: 'Global Signals',
    defaultTabId: 'alerts',
    tabs: [
      {
        id: 'alerts',
        label: 'Alerts',
        content: (
          <div className="inspector-stack">
            {card('Attention needed', renderTextList(riskyProjects.map((project) => `${project.name} · ${project.blocked_items} blocked / ${project.pending_approvals} approvals`)))}
          </div>
        ),
      },
      {
        id: 'progress',
        label: 'Progress',
        content: (
          <div className="inspector-stack">
            {card('Portfolio progress', renderTextList([
              `${data?.active_projects ?? 0} active projects`,
              `${data?.running_versions ?? 0} running versions`,
              `${data?.failed_runs ?? 0} failed runs need review`,
            ]))}
          </div>
        ),
      },
      {
        id: 'activity',
        label: 'Activity',
        content: (
          <div className="inspector-stack">
            {card('Recent movement', renderTextList((data?.projects ?? []).slice(0, 4).map((project) => `${project.name} · ${project.active_version}`)))}
          </div>
        ),
      },
    ],
  }
}

export function documentationInspectorRail(data?: DocumentationEntry[]): InspectorRailConfig {
  const categories = Array.from(new Set((data ?? []).map((entry) => entry.category)))
  return {
    title: 'Docs Navigator',
    defaultTabId: 'topics',
    tabs: [
      {
        id: 'topics',
        label: 'Topics',
        content: (
          <div className="inspector-stack">
            {card('Top topics', renderTextList((data ?? []).slice(0, 6).map((entry) => entry.title)))}
          </div>
        ),
      },
      {
        id: 'templates',
        label: 'Templates',
        content: (
          <div className="inspector-stack">
            {card('Reference templates', renderTextList(categories.map((category) => `${category} guides`)))}
          </div>
        ),
      },
      {
        id: 'updates',
        label: 'Updates',
        content: (
          <div className="inspector-stack">
            {card('Latest notes', renderTextList([
              'Routing is moving from the prototype container into real page modules.',
              'Agent-first flows remain the primary interaction model.',
            ]))}
          </div>
        ),
      },
    ],
  }
}

export function projectInspectorRail(data?: ProjectWorkspaceData): InspectorRailConfig {
  return {
    title: 'Project Context',
    defaultTabId: 'context',
    tabs: [
      {
        id: 'context',
        label: 'Context',
        content: (
          <div className="inspector-stack">
            {card('Project snapshot', renderTextList([
              `${data?.project.name ?? 'Project'} · ${data?.project.system_image_status ?? 'unknown image status'}`,
              `Active version · ${data?.project.active_version ?? 'none'}`,
              `Blocked items · ${data?.project.blocked_items ?? 0}`,
            ]))}
          </div>
        ),
      },
      {
        id: 'versions',
        label: 'Versions',
        content: (
          <div className="inspector-stack">
            {card('Version branches', renderTextList((data?.versions ?? []).map((version) => `${version.name} · ${version.branch_name}`)))}
          </div>
        ),
      },
      {
        id: 'activity',
        label: 'Activity',
        content: (
          <div className="inspector-stack">
            {card('US activity', renderTextList((data?.us_items ?? []).slice(0, 5).map((item) => `${item.id} · ${item.next_action}`)))}
          </div>
        ),
      },
    ],
  }
}

export function versionInspectorRail(data?: ProjectWorkspaceData): InspectorRailConfig {
  const version = data?.versions[0]
  return {
    title: 'Version Pulse',
    defaultTabId: 'board',
    tabs: [
      {
        id: 'board',
        label: 'Board',
        content: (
          <div className="inspector-stack">
            {card('Open US items', renderTextList((data?.us_items ?? []).map((item) => `${item.id} · ${item.status} · ${item.risk}`)))}
          </div>
        ),
      },
      {
        id: 'context',
        label: 'Context',
        content: (
          <div className="inspector-stack">
            {card('Release context', renderTextList([
              `${version?.name ?? 'No version'} · ${version?.branch_name ?? 'no branch'}`,
              `Pending runs · ${version?.pending_runs ?? 0}`,
              `Pending approvals · ${version?.pending_approvals ?? 0}`,
            ]))}
          </div>
        ),
      },
      {
        id: 'activity',
        label: 'Activity',
        content: (
          <div className="inspector-stack">
            {card('Recent actions', renderTextList((data?.us_items ?? []).slice(0, 4).map((item) => `${item.title} · ${item.owner}`)))}
          </div>
        ),
      },
    ],
  }
}

export function workspaceInspectorRail(data?: WorkspaceData): InspectorRailConfig {
  return {
    title: 'Asset Pack',
    defaultTabId: 'assets',
    tabs: [
      {
        id: 'assets',
        label: 'Assets',
        content: (
          <div className="inspector-stack">
            {card('Asset lanes', renderTextList((data?.asset_lanes ?? []).map((lane) => `${lane.label} · ${lane.status}`)))}
          </div>
        ),
      },
      {
        id: 'context',
        label: 'Context',
        content: (
          <div className="inspector-stack">
            {card('Workspace context', renderTextList([
              `${data?.project.name ?? 'Project'} · ${data?.version.name ?? 'Version'}`,
              `${data?.us_item.id ?? 'US'} · ${data?.us_item.title ?? 'Unknown work item'}`,
              `${data?.us_item.owner ?? 'Unassigned'} · ${data?.us_item.risk ?? 'unknown'} risk`,
            ]))}
          </div>
        ),
      },
      {
        id: 'activity',
        label: 'Activity',
        content: (
          <div className="inspector-stack">
            {card('Run queue', renderTextList((data?.runs ?? []).map((run) => `${run.title} · ${run.status}`)))}
          </div>
        ),
      },
    ],
  }
}

export function knowledgeInspectorRail(data?: KnowledgeObject[]): InspectorRailConfig {
  return {
    title: 'Knowledge Context',
    defaultTabId: 'graph',
    tabs: [
      {
        id: 'graph',
        label: 'Graph',
        content: (
          <div className="inspector-stack">
            {card('Graph focus', renderTextList((data ?? []).slice(0, 5).map((item) => `${item.name} · ${item.type}`)))}
          </div>
        ),
      },
      {
        id: 'objects',
        label: 'Objects',
        content: (
          <div className="inspector-stack">
            {card('Visible objects', renderTextList((data ?? []).map((item) => `${item.id} · ${item.branch}`)))}
          </div>
        ),
      },
      {
        id: 'search',
        label: 'Search',
        content: (
          <div className="inspector-stack">
            {card('Suggested queries', renderTextList([
              'Checkout flow',
              'Payment gateway fallback',
              'Release readiness blockers',
            ]))}
          </div>
        ),
      },
    ],
  }
}

export function runsInspectorRail(runs: { title: string; status: string; channel?: string }[] = []): InspectorRailConfig {
  return {
    title: 'Run Queue',
    defaultTabId: 'active',
    tabs: [
      {
        id: 'active',
        label: 'Active',
        content: (
          <div className="inspector-stack">
            {card('Run list', renderTextList(runs.map((run) => `${run.title} · ${run.status}`)))}
          </div>
        ),
      },
      {
        id: 'history',
        label: 'History',
        content: (
          <div className="inspector-stack">
            {card('Recent runs', renderTextList(runs.map((run) => `${run.title} · ${run.channel ?? 'web_runner'}`)))}
          </div>
        ),
      },
      {
        id: 'failed',
        label: 'Failed',
        content: (
          <div className="inspector-stack">
            {card('Failure focus', renderTextList(runs.filter((run) => run.status === 'failed').map((run) => run.title)))}
          </div>
        ),
      },
    ],
  }
}

export function governanceInspectorRail(items: { title: string; status: string }[] = []): InspectorRailConfig {
  return {
    title: 'Governance Queue',
    defaultTabId: 'pending',
    tabs: [
      {
        id: 'pending',
        label: 'Pending',
        content: (
          <div className="inspector-stack">
            {card('Pending decisions', renderTextList(items.map((item) => `${item.title} · ${item.status}`)))}
          </div>
        ),
      },
      {
        id: 'resolved',
        label: 'Resolved',
        content: (
          <div className="inspector-stack">
            {card('Resolved recently', renderTextList(['No recent resolved approvals in this slice yet']))}
          </div>
        ),
      },
      {
        id: 'policy',
        label: 'Policy',
        content: (
          <div className="inspector-stack">
            {card('Policy notes', renderTextList([
              'High-risk actions require approval or explicit confirmation.',
              'MergedResolution remains the only formal write path.',
            ]))}
          </div>
        ),
      },
    ],
  }
}

export function releaseInspectorRail(data?: ReleaseReadiness): InspectorRailConfig {
  return {
    title: 'Release Gate',
    defaultTabId: 'blockers',
    tabs: [
      {
        id: 'blockers',
        label: 'Blockers',
        content: (
          <div className="inspector-stack">
            {card('Blocking items', renderTextList(data?.blocker_items ?? ['No blocker items recorded']))}
          </div>
        ),
      },
      {
        id: 'signals',
        label: 'Signals',
        content: (
          <div className="inspector-stack">
            {card('Release signals', renderTextList([
              `Status · ${data?.status ?? 'unknown'}`,
              `Score · ${data?.score ?? 0}`,
              `Execution health · ${data?.execution_health ?? 'unknown'}`,
            ]))}
          </div>
        ),
      },
      {
        id: 'activity',
        label: 'Activity',
        content: (
          <div className="inspector-stack">
            {card('Gate activity', renderTextList([
              `${data?.approvals_open ?? 0} approvals open`,
              `${data?.pending_merge ?? 0} pending merge`,
            ]))}
          </div>
        ),
      },
    ],
  }
}
