import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ProjectRouteFrame } from '../project/ProjectRouteFrame'
import { ProjectWorkspaceView } from './ProjectWorkspaceView'
import type { AgentMode } from './ProjectWorkspaceTypes'

export function ProjectOverviewRoute() {
  const [params] = useSearchParams()
  const source = params.get('source')
  const sourceEntry = source === 'code' || source === 'usDoc' || source === 'testAsset' || source === 'all' ? source : undefined
  const [agentMode, setAgentMode] = useState<AgentMode>(sourceEntry ? 'sources' : 'planning')

  return (
    <ProjectRouteFrame>
      {(context, shellState) => (
        <ProjectWorkspaceView
          project={context.project}
          workspace={context.workspace}
          systemImage={context.systemImage}
          mode={agentMode}
          sourceEntry={sourceEntry}
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
          stopPrompt={context.stopPrompt}
          invokeProjectAction={context.invokeProjectAction}
          confirmPendingGoal={context.confirmPendingGoal}
          continueStructuralInvestigation={context.continueStructuralInvestigation}
          initializeSystemImage={context.initializeSystemImage}
          buildSystemImageFromSources={context.buildSystemImageFromSources}
          confirmToolInvocation={context.confirmToolInvocation}
          loading={context.loading}
          streaming={context.streaming}
          activeActionId={context.activeActionId}
          sidebarCollapsed={shellState.sidebarCollapsed}
          toggleSidebar={shellState.toggleSidebar}
        />
      )}
    </ProjectRouteFrame>
  )
}
