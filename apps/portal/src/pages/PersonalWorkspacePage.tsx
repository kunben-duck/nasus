import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { ProjectPageFrame } from '../app/PageFrames'
import { workspaceInspectorRail } from '../app/inspectorRails'
import { ActionComposer } from '../components/ActionComposer'
import { ChatTimeline } from '../components/ChatTimeline'
import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'
import { useConversation } from '../hooks/useConversation'

export function PersonalWorkspacePage() {
  const { projectId = '', usId = '' } = useParams()
  const workspaceQuery = useQuery({
    queryKey: ['workspace', projectId, usId],
    queryFn: () => api.getWorkspace(projectId, usId),
  })
  const { conversation, sendMessage } = useConversation('workspace', usId, `${usId} Workspace`)

  const data = workspaceQuery.data

  return (
    <ProjectPageFrame rail={workspaceInspectorRail(data)}>
      <Surface
        title={data?.us_item.title ?? 'Personal Workspace'}
        description="Conversation-first quality workspace for analysis, asset generation, execution preparation, and review."
      >
        <div className="section-grid two-up">
          <article className="panel-card">
            <p className="eyebrow">Quality asset pack</p>
            <div className="lane-stack">
              {data?.asset_lanes.map((lane) => (
                <div className="lane-card" key={lane.id}>
                  <div className="lane-header">
                    <h3>{lane.label}</h3>
                    <span className={`status-badge ${lane.status}`}>{lane.status}</span>
                  </div>
                  <p className="surface-description">{lane.summary}</p>
                  <span className="meta-text">{lane.updated_at}</span>
                </div>
              ))}
            </div>
          </article>
          <article className="panel-card">
            <p className="eyebrow">Conversation and agent loop</p>
            <div className="surface-actions" style={{ marginBottom: '12px' }}>
              <button
                className="ghost-button"
                type="button"
                data-action="generate_scenarios"
                onClick={() => void sendMessage('Generate scenarios for this US')}
              >
                Generate Scenarios
              </button>
            </div>
            <ChatTimeline messages={conversation?.messages ?? []} agentGoals={conversation?.agent_goals ?? []} />
            <ActionComposer
              placeholder="Generate, review, or revise quality assets for this US"
              suggestions={[
                'Generate scenarios for this US',
                'Summarize the current quality risk',
              ]}
              onSubmit={sendMessage}
            />
          </article>
        </div>
      </Surface>
    </ProjectPageFrame>
  )
}
