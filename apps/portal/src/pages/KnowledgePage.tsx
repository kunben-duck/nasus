import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { Surface } from '../components/WorkspaceShell'
import { api } from '../features/api'

export function KnowledgePage() {
  const { projectId = '' } = useParams()
  const knowledgeQuery = useQuery({
    queryKey: ['knowledge', projectId],
    queryFn: () => api.getKnowledge(projectId),
    enabled: Boolean(projectId),
  })

  return (
    <Surface
      title="Knowledge"
      description="Knowledge graph and object detail routes are now attached to the real app shell so system image objects can be inspected without falling back to the prototype container."
    >
      <article className="panel-card">
        <p className="eyebrow">Knowledge objects</p>
        <ul className="surface-list">
          {knowledgeQuery.data?.map((item) => (
            <li className="surface-row" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <p>{item.type} · {item.branch}</p>
              </div>
              <Link className="ghost-button" to={`/projects/${projectId}/knowledge/${item.id}`}>
                Open
              </Link>
            </li>
          ))}
        </ul>
      </article>
    </Surface>
  )
}
