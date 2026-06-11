import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useParams } from 'react-router-dom'

import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'
import type { RunSummary } from '../features/types'

export function RunsPage() {
  const { projectId = '' } = useParams()
  const runsQuery = useQuery({
    queryKey: ['runs', projectId],
    queryFn: () => api.getProjectRuns(projectId) as Promise<RunSummary[]>,
  })

  return (
    <Surface title="Runs" description="Canonical run list across the web execution channel.">
      <article className="panel-card">
        <p className="eyebrow">Run list</p>
        <ul className="surface-list">
          {runsQuery.data?.map((run) => (
            <li className="surface-row" key={run.id}>
              <div>
                <strong>{run.title}</strong>
                <p>{run.summary}</p>
              </div>
              <div className="row-actions">
                <span className={`status-badge ${run.status}`}>{run.status}</span>
                <span className="status-badge neutral">{run.channel}</span>
                <Link className="ghost-button" to={`/projects/${projectId}/runs/${run.id}`}>
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
