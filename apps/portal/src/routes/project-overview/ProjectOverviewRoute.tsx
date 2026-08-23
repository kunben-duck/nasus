import { useState } from 'react'

import { ProjectRouteFrame } from '../project/ProjectRouteFrame'
import { ProjectWorkspaceView } from './ProjectWorkspaceView'
import type { AgentMode } from './ProjectWorkspaceTypes'

export function ProjectOverviewRoute() {
  const [agentMode, setAgentMode] = useState<AgentMode>('planning')

  return (
    <ProjectRouteFrame>
      {(context, shellState) => (
        <ProjectWorkspaceView
          project={context.project}
          workspace={context.workspace}
          systemImage={context.systemImage}
          mode={agentMode}
          setMode={setAgentMode}
          messages={context.messages}
          agentGoal={context.agentGoal}
          agentGoalExplanation={context.agentGoalExplanation}
          memoryContext={context.memoryContext}
          swarmRuns={context.swarmRuns}
          toolInvocations={context.toolInvocations}
          pendingGoal={context.pendingGoal}
          prompt={context.prompt}
          setPrompt={context.setPrompt}
          runPrompt={context.runPrompt}
          invokeProjectAction={context.invokeProjectAction}
          confirmPendingGoal={context.confirmPendingGoal}
          initializeSystemImage={context.initializeSystemImage}
          buildSystemImageFromSources={context.buildSystemImageFromSources}
          confirmToolInvocation={context.confirmToolInvocation}
          loading={context.loading}
          activeActionId={context.activeActionId}
          sidebarCollapsed={shellState.sidebarCollapsed}
          toggleSidebar={shellState.toggleSidebar}
        />
      )}
    </ProjectRouteFrame>
  )
}
