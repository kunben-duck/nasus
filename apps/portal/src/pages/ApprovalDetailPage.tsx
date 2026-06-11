import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'

export function ApprovalDetailPage() {
  const { projectId = '', approvalId = '' } = useParams()
  const detailQuery = useQuery({
    queryKey: ['approval-detail', projectId, approvalId],
    queryFn: () => api.getApprovalDetail(projectId, approvalId),
  })

  const approval = detailQuery.data

  return (
    <Surface
      title={approval?.title ?? 'Approval Detail'}
      description={approval?.summary ?? 'Review policy reasoning, conflicting fields, and recommended resolution.'}
    >
      <div className="section-grid two-up">
        <article className="panel-card">
          <p className="eyebrow">Policy reason</p>
          <p className="surface-description">{approval?.policy_reason ?? 'No policy details available.'}</p>
        </article>
        <article className="panel-card">
          <p className="eyebrow">Recommended resolution</p>
          <p className="surface-description">{approval?.recommended_resolution ?? 'No recommendation available.'}</p>
        </article>
      </div>
      <div className="section-grid two-up">
        <article className="panel-card">
          <p className="eyebrow">Conflict fields</p>
          <ul className="simple-list">
            {approval?.conflict_fields.map((field) => <li key={field}>{field}</li>)}
          </ul>
        </article>
        <article className="panel-card">
          <p className="eyebrow">Evidence</p>
          <ul className="simple-list">
            {approval?.evidence.map((entry) => <li key={entry}>{entry}</li>)}
          </ul>
        </article>
      </div>
    </Surface>
  )
}
