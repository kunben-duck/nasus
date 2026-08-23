import type { StudioActionId } from '../../domains/platform/tool-actions'
import type { AgentMode } from './ProjectWorkspaceTypes'
import type { AgentCardTitle } from './components/agentCards'

export function createProjectWorkspaceCardActions({
  setMode,
  initializeSystemImage,
  invokeProjectAction,
}: {
  setMode: (mode: AgentMode) => void
  initializeSystemImage: () => void
  invokeProjectAction: (actionId: StudioActionId, input?: Record<string, unknown>) => void
}): Record<AgentCardTitle, () => void> {
  return {
    'System Image Builder': () => {
      setMode('sources')
      initializeSystemImage()
    },
    'Quality Loop Agent': () => invokeProjectAction('quality-loop.continue-goal'),
    'Release Assessor': () => invokeProjectAction('release.assess'),
    'Repo Maintainer': () => invokeProjectAction('system-image.status'),
  }
}
