import type { ProjectRouteContext } from './ProjectRouteTypes'
import { useProjectConversationModel } from './useProjectConversationModel'
import { useProjectRouteActions } from './useProjectRouteActions'
import { useProjectRouteData } from './useProjectRouteData'

export function useProjectRouteContext() {
  const routeData = useProjectRouteData()
  const project = routeData.project
  const {
    projectConversation,
    pausedProjectGoal,
    latestProjectGoal,
    agentGoalExplanation,
    memoryContext,
    swarmRuns,
    visibleMessages,
  } =
    useProjectConversationModel(project)
  const projectActions = useProjectRouteActions({
    project,
    projectConversation,
    pausedProjectGoal,
  })
  const context: ProjectRouteContext | undefined = project
    ? {
        projectId: routeData.projectId,
        project,
        workspace: routeData.workspace,
        systemImage: routeData.systemImage,
        releaseReadiness: routeData.releaseReadiness,
        messages: visibleMessages,
        agentGoal: latestProjectGoal,
        agentGoalExplanation,
        memoryContext,
        swarmRuns,
        toolInvocations: projectConversation.conversation?.tool_invocations ?? [],
        pendingGoal: pausedProjectGoal,
        ...projectActions,
      }
    : undefined

  return {
    projectId: routeData.projectId,
    project: routeData.project,
    systemImage: routeData.systemImage,
    projectStatusDependency: routeData.projectStatusDependency,
    context,
    projectLoading: routeData.projectLoading,
    backToDashboard: routeData.backToDashboard,
  }
}
