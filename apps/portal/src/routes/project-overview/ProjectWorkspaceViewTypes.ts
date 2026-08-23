import type { AgentGoal, AgentGoalExplanation, AgentMemoryContextView, AgentSwarmRun } from '../../domains/agent/types'
import type { ProjectWorkspaceData } from '../../domains/quality-loop/types'
import type { ProjectCard, ToolInvocation } from '../../domains/platform/types'
import type { StudioActionId } from '../../domains/platform/tool-actions'
import type { SystemImageData } from '../../domains/system-image/types'
import type { AgentMode, MessageRow } from './ProjectWorkspaceTypes'
import type { SourceBindingValues } from './components/sourceBindingDefaults'

export interface ProjectWorkspaceViewProps {
  project: ProjectCard
  workspace?: ProjectWorkspaceData
  systemImage?: SystemImageData
  mode: AgentMode
  setMode: (mode: AgentMode) => void
  messages: MessageRow[]
  agentGoal?: AgentGoal
  agentGoalExplanation?: AgentGoalExplanation
  memoryContext?: AgentMemoryContextView
  swarmRuns: AgentSwarmRun[]
  toolInvocations: ToolInvocation[]
  pendingGoal?: AgentGoal
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  invokeProjectAction: (actionId: StudioActionId, input?: Record<string, unknown>) => void
  confirmPendingGoal: () => void
  initializeSystemImage: () => void
  buildSystemImageFromSources: (sources: SourceBindingValues) => void
  confirmToolInvocation: (invocationId: string) => void
  loading: boolean
  activeActionId: string | null
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}
