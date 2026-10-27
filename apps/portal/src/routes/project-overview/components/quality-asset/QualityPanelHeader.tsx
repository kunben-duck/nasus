import type { QualityPanelHeaderView } from '../../projectWorkspaceSelectors'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function QualityPanelHeader({ header }: { header: QualityPanelHeaderView }) {
  const { t, tx } = useI18n()
  return (
    <div className="quality-panel-header">
      <div>
        <span className="eyebrow">{t('Quality loop')}</span>
        <strong>{tx(header.title)}</strong>
        <p>{tx(header.summary)}</p>
      </div>
      {header.qualityStatus ? (
        <span className={`quality-state-pill ${header.qualityStatus}`}>{tx(header.qualityStatus.replaceAll('_', ' '))}</span>
      ) : header.latestRunStatus ? (
        <span className={`run-status-pill ${header.latestRunStatus}`}>{tx(header.latestRunStatus)}</span>
      ) : null}
    </div>
  )
}
