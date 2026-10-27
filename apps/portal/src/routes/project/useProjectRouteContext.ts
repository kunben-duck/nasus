import type { ProjectRouteContext } from './ProjectRouteTypes'
import { useProjectConversationModel } from './useProjectConversationModel'
import { useProjectRouteActions } from './useProjectRouteActions'
import { useProjectRouteData } from './useProjectRouteData'
import { useSearchParams } from 'react-router-dom'

export function useProjectRouteContext() {
  const [params] = useSearchParams()
  // Review navigation must not create a conversation before its original
  // goal, command, source permissions and candidate have been verified.
  const reviewingBuild = params.has('build_review_goal') || params.has('build_review_invocation')
  const routeData = useProjectRouteData({ reviewingBuild })
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
    useProjectConversationModel(project, { existingOnly: reviewingBuild, canReadWorkspace: routeData.canReadWorkspace })
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
        systemImageError: routeData.systemImageError,
        reviewingBuild,
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
