import type { QualityPanelHeaderView } from '../../projectWorkspaceSelectors'

export function QualityPanelHeader({ header }: { header: QualityPanelHeaderView }) {
  return (
    <div className="quality-panel-header">
      <div>
        <span className="eyebrow">Quality loop</span>
        <strong>{header.title}</strong>
        <p>{header.summary}</p>
      </div>
      {header.qualityStatus ? (
        <span className={`quality-state-pill ${header.qualityStatus}`}>{header.qualityStatus.replaceAll('_', ' ')}</span>
      ) : header.latestRunStatus ? (
        <span className={`run-status-pill ${header.latestRunStatus}`}>{header.latestRunStatus}</span>
      ) : null}
    </div>
  )
}
