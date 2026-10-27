import { matchPath } from 'react-router-dom'
import type { MessageKey } from '../../shared/i18n/messages'

export const projectFeatureNavigation = {
  'system-image': {
    path: '/system-image',
    label: 'System image',
    description: 'Choose a project to inspect its system image and source evidence.',
    projectSection: 'knowledge',
  },
  'quality-loops': {
    path: '/quality-loops',
    label: 'Quality loops',
    description: 'Choose a project to review versions, user stories and quality progress.',
    projectSection: 'versions',
  },
  runs: {
    path: '/runs',
    label: 'Runs',
    description: 'Choose a project to inspect its execution records.',
    projectSection: 'runs',
  },
} as const satisfies Record<string, {
  path: string
  label: MessageKey
  description: MessageKey
  projectSection: string
}>

export type ProjectFeatureKey = keyof typeof projectFeatureNavigation
export type TopLevelNavKey = 'build' | 'dashboard' | 'documentation' | ProjectFeatureKey
export type ProjectNavKey = ProjectFeatureKey | 'agent-workspace' | 'governance' | 'release-readiness'

export function projectNavigationPath(projectId: string, key: ProjectNavKey) {
  const base = `/projects/${encodeURIComponent(projectId)}`
  if (key === 'agent-workspace') return base
  if (key === 'governance' || key === 'release-readiness') return `${base}/${key}`
  return `${base}/${projectFeatureNavigation[key].projectSection}`
}

export function activeProjectNavKey(pathname: string): ProjectNavKey | null {
  const match = matchPath('/projects/:projectId/*', pathname)
  if (!match) return null
  const section = (match.params['*'] ?? '').split('/')[0]
  switch (section) {
    case '': return 'agent-workspace'
    case 'knowledge': return 'system-image'
    case 'versions':
    case 'workspaces': return 'quality-loops'
    case 'runs': return 'runs'
    case 'governance':
    case 'approvals': return 'governance'
    case 'release-readiness': return 'release-readiness'
    default: return null
  }
}
