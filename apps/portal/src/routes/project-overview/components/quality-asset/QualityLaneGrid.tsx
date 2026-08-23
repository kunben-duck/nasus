import type { QualityLaneCardView } from '../../projectWorkspaceSelectors'

export function QualityLaneGrid({ lanes }: { lanes: QualityLaneCardView[] }) {
  if (!lanes.length) {
    return (
      <div className="quality-empty-state">
        No quality asset lanes yet. Ask Nasus to build the system image or import US documents first.
      </div>
    )
  }

  return (
    <div className="quality-lane-grid">
      {lanes.map((lane) => (
        <div className={`quality-lane-card ${lane.status}`} key={lane.id}>
          <div>
            <span className="quality-lane-dot" />
            <strong>{lane.label}</strong>
          </div>
          <p>{lane.summary}</p>
          <span>{lane.statusLabel}</span>
        </div>
      ))}
    </div>
  )
}
