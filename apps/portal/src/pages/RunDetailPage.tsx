import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'

export function RunDetailPage() {
  const { projectId = '', runId = '' } = useParams()
  const detailQuery = useQuery({
    queryKey: ['run-detail', projectId, runId],
    queryFn: () => api.getRunDetail(projectId, runId),
  })

  const run = detailQuery.data

  return (
    <Surface
      title={run?.title ?? 'Run Detail'}
      description={run?.summary ?? 'Execution trace, evidence, and healing detail for a canonical run.'}
    >
      <div className="metrics-grid compact">
        <div className="metric-card"><strong>{run?.status ?? '—'}</strong><span>Status</span></div>
        <div className="metric-card"><strong>{run?.channel ?? '—'}</strong><span>Channel</span></div>
        <div className="metric-card"><strong>{run?.healing_status ?? '—'}</strong><span>Healing</span></div>
      </div>
      <div className="section-grid two-up">
        <article className="panel-card">
          <p className="eyebrow">Timeline</p>
          <ul className="simple-list">
            {run?.timeline.map((entry) => <li key={entry}>{entry}</li>)}
          </ul>
        </article>
        <article className="panel-card">
          <p className="eyebrow">Evidence</p>
          <ul className="simple-list">
            {run?.evidence.map((entry) => <li key={entry}>{entry}</li>)}
          </ul>
        </article>
      </div>
      <article className="panel-card">
        <p className="eyebrow">Failure analysis</p>
        <p className="surface-description">{run?.failure_summary ?? 'No failure summary available.'}</p>
      </article>
    </Surface>
  )
}
