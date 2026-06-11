import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'

export function KnowledgeDetailPage() {
  const { projectId = '', objectId = '' } = useParams()
  const detailQuery = useQuery({
    queryKey: ['knowledge', projectId, objectId],
    queryFn: () => api.getKnowledgeDetail(projectId, objectId),
  })

  const item = detailQuery.data

  return (
    <Surface
      title={item ? `${item.name} Object Detail` : 'Knowledge Object Detail'}
      description="Trace the object, its branch state, and the evidence chain that supports it."
    >
      <div className="section-grid two-up">
        <article className="panel-card">
          <p className="eyebrow">Object summary</p>
          <ul className="surface-list">
            <li className="surface-row">
              <div>
                <strong>Type</strong>
                <p>{item?.type ?? '—'}</p>
              </div>
              <span className="status-badge neutral">{item?.branch ?? 'unknown'}</span>
            </li>
            <li className="surface-row">
              <div>
                <strong>Confidence</strong>
                <p>{item?.confidence ?? '—'}</p>
              </div>
              <span className="status-badge neutral">{item?.freshness ?? '—'}</span>
            </li>
          </ul>
        </article>
        <article className="panel-card">
          <p className="eyebrow">Relationships</p>
          <ul className="simple-list">
            {item?.relations.map((relation) => <li key={relation}>{relation}</li>)}
          </ul>
        </article>
      </div>
      <article className="panel-card">
        <p className="eyebrow">Evidence trail</p>
        <ul className="simple-list">
          {item?.evidence.map((entry) => <li key={entry}>{entry}</li>)}
        </ul>
      </article>
    </Surface>
  )
}
