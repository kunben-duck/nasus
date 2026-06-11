import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { ProjectPageFrame } from '../app/PageFrames'
import { projectInspectorRail } from '../app/inspectorRails'
import { ConversationWorkspaceCard } from '../components/ConversationWorkspaceCard'
import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'
import { useConversation } from '../hooks/useConversation'

export function ProjectOverviewPage() {
  const { projectId = '' } = useParams()
  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.getProject(projectId),
  })
  const projectName = projectQuery.data?.project.name ?? 'Project Overview'
  const { conversation, sendMessage } = useConversation('project', projectId, projectName)

  const data = projectQuery.data
  const primaryUs = data?.us_items[0]
  const connectedSources = [
    'Git · payment-system / checkout-ui',
    'US Docs · PRD bundle and acceptance notes',
    'UX Boards · checkout, refund, fallback states',
    'Historical Assets · regression and flaky failure history',
  ]

  return (
    <ProjectPageFrame rail={projectInspectorRail(data)}>
      <Surface
        title={data?.project.name ?? 'Project Overview'}
        description={data?.project.summary ?? 'Loading project context'}
        actions={
          <div className="surface-actions">
            <Link className="primary-button" data-action="open_versions" to={`/projects/${projectId}/versions`}>
              Open Version Space
            </Link>
            {primaryUs ? (
              <Link className="ghost-button" data-action="open_workspace" data-us={primaryUs.id} to={`/projects/${projectId}/workspaces/${primaryUs.id}`}>
                Open Workspace
              </Link>
            ) : null}
          </div>
        }
      >
        <div className="metrics-grid">
          <div className="metric-card"><strong>{data?.project.system_image_status ?? '—'}</strong><span>System image</span></div>
          <div className="metric-card"><strong>{data?.project.active_version ?? '—'}</strong><span>Active version</span></div>
          <div className="metric-card"><strong>{data?.project.blocked_items ?? 0}</strong><span>Blocked items</span></div>
          <div className="metric-card"><strong>{data?.project.pending_approvals ?? 0}</strong><span>Pending approvals</span></div>
        </div>
        <div className="section-grid two-up">
          <ConversationWorkspaceCard
            title="Project conversation"
            placeholder="Ask Nasus to review project status, refresh imports, or create a version branch"
            suggestions={[
              'Summarize the current project status',
              'Create version branch "2026.Q3" for this project',
            ]}
            messages={conversation?.messages ?? []}
            agentGoals={conversation?.agent_goals ?? []}
            onSubmit={sendMessage}
            compact
          />
          <div className="stacked-panels">
            <article className="panel-card">
              <p className="eyebrow">Project command center</p>
              <div className="suggestion-row">
                <Link className="ghost-button" to={`/projects/${projectId}/versions/create`}>
                  Create Version Branch
                </Link>
                <button className="ghost-button" type="button" onClick={() => void sendMessage('Refresh the system image for this project')}>
                  Refresh System Image
                </button>
                <Link className="ghost-button" to={`/projects/${projectId}/knowledge`}>
                  Open Knowledge
                </Link>
              </div>
            </article>
            <article className="panel-card">
              <p className="eyebrow">Connected sources</p>
              <ul className="surface-list">
                {connectedSources.map((source) => (
                  <li className="surface-row" key={source}>
                    <div>
                      <strong>{source}</strong>
                      <p>Connected and queryable</p>
                    </div>
                    <span className="status-badge approved">ready</span>
                  </li>
                ))}
              </ul>
            </article>
          </div>
        </div>
        <div className="section-grid two-up">
          <article className="panel-card">
            <p className="eyebrow">Versions</p>
            <ul className="surface-list">
              {data?.versions.map((version) => (
                <li className="surface-row" key={version.id}>
                  <div>
                    <strong>{version.name}</strong>
                    <p>{version.branch_name}</p>
                  </div>
                  <span className="status-badge neutral">{version.status}</span>
                </li>
              ))}
            </ul>
          </article>
          <article className="panel-card">
            <p className="eyebrow">US items</p>
            <ul className="surface-list">
              {data?.us_items.map((item) => (
                <li className="surface-row" key={item.id}>
                  <div>
                    <strong>{item.id} · {item.title}</strong>
                    <p>{item.owner} · {item.next_action}</p>
                  </div>
                  <Link className="ghost-button" role="button" data-action="open_workspace" data-us={item.id} to={`/projects/${projectId}/workspaces/${item.id}`}>
                    Open
                  </Link>
                </li>
              ))}
            </ul>
          </article>
        </div>
      </Surface>
    </ProjectPageFrame>
  )
}
