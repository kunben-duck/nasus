import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useParams } from 'react-router-dom'

import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'
import type { ApprovalSummary } from '../features/types'

export function GovernancePage() {
  const { projectId = '' } = useParams()
  const approvalsQuery = useQuery({
    queryKey: ['approvals', projectId],
    queryFn: () => api.getProjectApprovals(projectId) as Promise<ApprovalSummary[]>,
  })

  return (
    <Surface title="Governance" description="Approvals, merge gates, and release readiness flow from the same project-space shell.">
      <article className="panel-card">
        <p className="eyebrow">Pending approvals</p>
        <ul className="surface-list">
          {approvalsQuery.data?.map((approval) => (
            <li className="surface-row" key={approval.id}>
              <div>
                <strong>{approval.title}</strong>
                <p>{approval.summary}</p>
              </div>
              <div className="row-actions">
                <span className={`status-badge ${approval.status}`}>{approval.status}</span>
                <Link className="ghost-button" to={`/projects/${projectId}/governance/${approval.id}`}>
                  Open
                </Link>
              </div>
            </li>
          ))}
        </ul>
      </article>
    </Surface>
  )
}
