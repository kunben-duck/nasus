import type { ProjectCard } from '../../../domains/platform/types'
import type { SystemImageData } from '../../../domains/system-image/types'

export function SystemImageStrip({ systemImage, project }: { systemImage?: SystemImageData; project: ProjectCard }) {
  const sourceCount = systemImage?.sources.length ?? 0
  const indexed = systemImage?.sources.filter((source) => source.ingestion_status === 'indexed').length ?? 0
  const metricGroups = systemImage?.metric_snapshots.map((metric) => metric.metric_group) ?? []
  const status = systemImage?.project.system_image_status ?? project.system_image_status
  const buildState = systemImage?.build_state
  const stages = ['Sources', 'Ingest', 'Index', 'Context', 'Baseline']

  return (
    <div className="system-image-strip" data-testid="system-image-strip">
      <div>
        <span className="eyebrow">System image</span>
        <div className="system-image-title-row">
          <strong>{status}</strong>
          {buildState ? <span className={`system-image-state ${buildState.status}`}>{buildState.status.replaceAll('_', ' ')}</span> : null}
        </div>
        <p>{systemImage?.summary ?? 'Waiting for source ingestion and baseline initialization.'}</p>
        {buildState ? <div className="system-image-build-label">{buildState.label}</div> : null}
        {buildState ? (
          <div className="system-image-stage-bar" aria-label="System image build state">
            {stages.map((stage, index) => {
              const stageNumber = index + 1
              const active = buildState.stage_index >= stageNumber
              return (
                <span className={active ? 'active' : ''} key={stage}>
                  <i />
                  {stage}
                </span>
              )
            })}
          </div>
        ) : null}
        {buildState?.missing_source_types.length ? (
          <div className="system-image-hint">
            Missing sources: {buildState.missing_source_types.join(', ')}
          </div>
        ) : null}
        {buildState?.failed_source_ids.length ? (
          <div className="system-image-hint failed">
            Failed sources: {buildState.failed_source_ids.join(', ')}
          </div>
        ) : null}
      </div>
      <div className="source-stat-grid">
        <MetricMini label="Sources indexed" value={`${indexed}/${sourceCount || 3}`} />
        <MetricMini label="Objects" value={`${systemImage?.objects.length ?? 0}`} />
        <MetricMini label="Relations" value={`${systemImage?.relationships.length ?? 0}`} />
        <MetricMini label="Metrics" value={`${metricGroups.length}`} />
      </div>
    </div>
  )
}

function MetricMini({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-mini">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}
