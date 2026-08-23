import type { QualityAssetPanelView } from '../projectWorkspaceSelectors'
import { LatestRunRow } from './quality-asset/LatestRunRow'
import { QualityLaneGrid } from './quality-asset/QualityLaneGrid'
import { QualityLoopStateCard } from './quality-asset/QualityLoopStateCard'
import { QualityPanelHeader } from './quality-asset/QualityPanelHeader'

export function QualityAssetPanel({ model }: { model?: QualityAssetPanelView }) {
  if (!model) {
    return null
  }

  return (
    <div className="quality-asset-panel" data-testid="quality-asset-panel">
      <QualityPanelHeader header={model.header} />
      <QualityLoopStateCard qualityState={model.qualityState} />
      <QualityLaneGrid lanes={model.lanes} />
      <LatestRunRow latestRun={model.latestRun} />
    </div>
  )
}
