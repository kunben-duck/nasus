import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { ProjectPageFrame } from '../app/PageFrames'
import { versionInspectorRail } from '../app/inspectorRails'
import { ConversationWorkspaceCard } from '../components/ConversationWorkspaceCard'
import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'
import { useConversation } from '../hooks/useConversation'

export function VersionSpacePage() {
  const { projectId = '' } = useParams()
  const projectQuery = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.getProject(projectId),
  })
  const currentVersionId = projectQuery.data?.versions[0]?.id ?? `${projectId}-version`
  const currentVersionName = projectQuery.data?.versions[0]?.name ?? 'Version Space'
  const { conversation, sendMessage } = useConversation('version', currentVersionId, currentVersionName)

  return (
    <ProjectPageFrame rail={versionInspectorRail(projectQuery.data)}>
      <Surface
        title="Version Space"
        description="Version-level US board, ownership, and risk posture for the active release branch."
      >
        <div className="metrics-grid">
          <div className="metric-card"><strong>{projectQuery.data?.versions[0]?.name ?? '—'}</strong><span>Active version</span></div>
          <div className="metric-card"><strong>{projectQuery.data?.versions[0]?.us_total ?? projectQuery.data?.us_items.length ?? 0}</strong><span>Open US</span></div>
          <div className="metric-card"><strong>{projectQuery.data?.versions[0]?.pending_approvals ?? 0}</strong><span>Pending approvals</span></div>
          <div className="metric-card"><strong>{projectQuery.data?.versions[0]?.pending_runs ?? 0}</strong><span>Pending runs</span></div>
        </div>
        <div className="section-grid two-up">
          <ConversationWorkspaceCard
            title="Version conversation"
            placeholder="Ask for version progress, blockers, risk, or owner-level closure"
            suggestions={[
              'Summarize the current version closure status',
              'Which US items are still high risk?',
            ]}
            messages={conversation?.messages ?? []}
            agentGoals={conversation?.agent_goals ?? []}
            onSubmit={sendMessage}
            compact
          />
          <div className="stacked-panels">
            <article className="panel-card">
              <p className="eyebrow">Version board</p>
              <div className="suggestion-row">
                <Link className="ghost-button" to={`/projects/${projectId}/versions/create`}>
                  Create Version Branch
                </Link>
                <button className="ghost-button" type="button" onClick={() => void sendMessage('Generate version risk for the active release branch')}>
                  Generate Version Risk
                </button>
                <Link className="ghost-button" to={`/projects/${projectId}/release-readiness`}>
                  Release Readiness
                </Link>
              </div>
            </article>
            <article className="panel-card">
              <p className="eyebrow">Version summary</p>
              {projectQuery.data?.versions.map((version) => (
                <div className="summary-block" key={version.id}>
                  <h3>{version.name}</h3>
                  <p className="surface-description">{version.branch_name}</p>
                  <div className="metrics-grid compact">
                    <div className="metric-card"><strong>{version.us_total}</strong><span>US total</span></div>
                    <div className="metric-card"><strong>{version.us_closed}</strong><span>Closed</span></div>
                    <div className="metric-card"><strong>{version.pending_runs}</strong><span>Pending runs</span></div>
                  </div>
                </div>
              ))}
            </article>
          </div>
        </div>
        <div className="section-grid two-up">
          <article className="panel-card">
            <p className="eyebrow">US board</p>
            <ul className="surface-list">
              {projectQuery.data?.us_items.map((item) => (
                <li className="surface-row" key={item.id}>
                  <div>
                    <strong>{item.id} · {item.title}</strong>
                    <p>{item.owner} · {item.status}</p>
                  </div>
                  <div className="row-actions">
                    <span className={`status-badge ${item.risk}`}>{item.risk}</span>
                    <span className="status-badge analysis">{item.progress}%</span>
                    <Link className="ghost-button" data-action="open_workspace" data-us={item.id} to={`/projects/${projectId}/workspaces/${item.id}`}>
                      Open
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          </article>
        </div>
      </Surface>
    </ProjectPageFrame>
  )
}
