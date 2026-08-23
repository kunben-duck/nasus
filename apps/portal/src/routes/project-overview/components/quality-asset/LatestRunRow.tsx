import type { QualityLatestRunView } from '../../projectWorkspaceSelectors'

export function LatestRunRow({ latestRun }: { latestRun?: QualityLatestRunView }) {
  if (!latestRun) return null

  return (
    <div className="quality-run-row">
      <span>Latest run</span>
      <strong>{latestRun.title}</strong>
      <p>{latestRun.summary}</p>
    </div>
  )
}
