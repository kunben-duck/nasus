import type { QualityLaneCardView } from '../../projectWorkspaceSelectors'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function QualityLaneGrid({ lanes }: { lanes: QualityLaneCardView[] }) {
  const { t, tx } = useI18n()
  if (!lanes.length) {
    return (
      <div className="quality-empty-state">
        {t('No quality asset lanes yet. Ask Nasus to build the system image or import US documents first.')}
      </div>
    )
  }

  return (
    <div className="quality-lane-grid">
      {lanes.map((lane) => (
        <div className={`quality-lane-card ${lane.status}`} key={lane.id}>
          <div>
            <span className="quality-lane-dot" />
            <strong>{tx(lane.label)}</strong>
          </div>
          <p>{tx(lane.summary)}</p>
          <span>{tx(lane.statusLabel)}</span>
        </div>
      ))}
    </div>
  )
}
