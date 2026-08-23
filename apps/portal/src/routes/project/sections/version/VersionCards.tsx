import { Link } from 'react-router-dom'

import type { USItem, VersionSummary } from '../../../../domains/quality-loop/types'

export function VersionList({ versions }: { versions: VersionSummary[] }) {
  if (!versions.length) return null

  return (
    <div className="quality-lane-grid">
      {versions.map((version) => (
        <div className="quality-lane-card ready" key={version.id}>
          <div>
            <span className="quality-lane-dot" />
            <strong>{version.name}</strong>
          </div>
          <p>{version.branch_name}</p>
          <span>
            {version.status} · {version.us_closed}/{version.us_total} US closed
          </span>
        </div>
      ))}
    </div>
  )
}

export function USCard({ item, projectId }: { item: USItem; projectId: string }) {
  return (
    <Link className={`quality-lane-card ${item.status}`} to={`/projects/${projectId}/workspaces/${encodeURIComponent(item.id)}`}>
      <div>
        <span className="quality-lane-dot" />
        <strong>
          {item.id} · {item.title}
        </strong>
      </div>
      <p>
        {item.owner} · {item.next_action}
      </p>
      <span>
        {item.risk} · {item.progress}%
      </span>
    </Link>
  )
}
