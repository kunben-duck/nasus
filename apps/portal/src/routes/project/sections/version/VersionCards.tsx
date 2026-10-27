import { Link } from 'react-router-dom'

import type { USItem, VersionSummary } from '../../../../domains/quality-loop/types'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function VersionList({ versions }: { versions: VersionSummary[] }) {
  const { t, tx } = useI18n()
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
            {tx(version.status)} · {t('{closed}/{total} US closed', { closed: version.us_closed, total: version.us_total })}
          </span>
        </div>
      ))}
    </div>
  )
}

export function USCard({ item, projectId }: { item: USItem; projectId: string }) {
  const { tx } = useI18n()
  return (
    <Link className={`quality-lane-card ${item.status}`} to={`/projects/${projectId}/workspaces/${encodeURIComponent(item.id)}`}>
      <div>
        <span className="quality-lane-dot" />
        <strong>
          {item.id} · {tx(item.title)}
        </strong>
      </div>
      <p>
        {item.owner} · {tx(item.next_action)}
      </p>
      <span>
        {tx(item.risk)} · {item.progress}%
      </span>
    </Link>
  )
}
