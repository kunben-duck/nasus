import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'

export function ReleaseReadinessPage() {
  const { projectId = '' } = useParams()
  const readinessQuery = useQuery({
    queryKey: ['release-readiness', projectId],
    queryFn: () => api.getReleaseReadiness(projectId),
  })

  const readiness = readinessQuery.data

  return (
    <Surface
      title="Release Readiness"
      description={readiness?.summary ?? 'Version-level release posture, blockers, and execution health.'}
    >
      <div className="metrics-grid">
        <div className="metric-card"><strong>{readiness?.status ?? '—'}</strong><span>Status</span></div>
        <div className="metric-card"><strong>{readiness?.score ?? 0}</strong><span>Score</span></div>
        <div className="metric-card"><strong>{readiness?.blockers ?? 0}</strong><span>Blockers</span></div>
        <div className="metric-card"><strong>{readiness?.approvals_open ?? 0}</strong><span>Approvals</span></div>
        <div className="metric-card"><strong>{readiness?.pending_merge ?? 0}</strong><span>Pending merge</span></div>
      </div>
      <article className="panel-card">
        <p className="eyebrow">Execution health</p>
        <p className="surface-description">{readiness?.execution_health ?? 'No execution health available.'}</p>
      </article>
      <article className="panel-card">
        <p className="eyebrow">Blocker items</p>
        <ul className="simple-list">
          {readiness?.blocker_items.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </article>
    </Surface>
  )
}
