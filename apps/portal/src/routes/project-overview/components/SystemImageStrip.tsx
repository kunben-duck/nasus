import type { ProjectCard } from '../../../domains/platform/types'
import type { SystemImageData } from '../../../domains/system-image/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { SourceVisibilityNotice } from '../../../shared/ui/SourceVisibilityNotice'
import { MetricMini } from '../../../shared/ui/MetricMini'

export function SystemImageStrip({ systemImage, project }: { systemImage?: SystemImageData; project: ProjectCard }) {
  const { t, tx } = useI18n()
  const sourceCount = systemImage?.sources.length ?? 0
  const indexed = systemImage?.sources.filter((source) => source.ingestion_status === 'indexed').length ?? 0
  const metricGroups = systemImage?.metric_snapshots.map((metric) => metric.metric_group) ?? []
  const limited = systemImage?.visibility?.mode === 'source_filtered'
  const status = limited ? t('Source-filtered view') : systemImage?.project.system_image_status ?? project.system_image_status
  const buildState = systemImage?.build_state
  const stages = ['Sources', 'Ingest', 'Index', 'Context', 'Baseline']

  return (
    <div className="system-image-strip" data-testid="system-image-strip">
      <div>
        <span className="eyebrow">{t('System image')}</span>
        {!limited && <div className="system-image-title-row">
          <strong>{tx(status)}</strong>
          {buildState && !limited ? <span className={`system-image-state ${buildState.status}`}>{tx(buildState.status.replaceAll('_', ' '))}</span> : null}
        </div>}
        {!limited && <p>{systemImage?.summary ? tx(systemImage.summary) : t('Waiting for source ingestion and baseline initialization.')}</p>}
        {buildState && !limited ? <div className="system-image-build-label">{tx(buildState.label)}</div> : null}
        <SourceVisibilityNotice limited={limited} />
        {buildState && !limited ? (
          <div className="system-image-stage-bar" aria-label={t('System image build state')}>
            {stages.map((stage, index) => {
              const stageNumber = index + 1
              const active = buildState.stage_index !== null && buildState.stage_index >= stageNumber
              return (
                <span className={active ? 'active' : ''} key={stage}>
                  <i />
                  {tx(stage)}
                </span>
              )
            })}
          </div>
        ) : null}
        {buildState?.missing_source_types.length ? (
          <div className="system-image-hint">
            {t('Missing sources: {sources}', {
              sources: buildState.missing_source_types.map((source) => tx(source)).join('、'),
            })}
          </div>
        ) : null}
        {buildState?.failed_source_ids.length ? (
          <div className="system-image-hint failed">
            {t('Failed sources: {sources}', { sources: buildState.failed_source_ids.join('、') })}
          </div>
        ) : null}
      </div>
      <div className="source-stat-grid">
        <MetricMini label={t(limited ? 'Visible sources indexed' : 'Sources indexed')} value={`${indexed}/${limited ? sourceCount : sourceCount || 3}`} />
        <MetricMini label={t(limited ? 'Visible objects' : 'Objects')} value={`${systemImage?.objects.length ?? 0}`} />
        <MetricMini label={t('Relations')} unavailable={limited} value={limited ? t('Unavailable') : `${systemImage?.relationships.length ?? 0}`} />
        <MetricMini label={t('Metrics')} unavailable={limited} value={limited ? t('Unavailable') : `${metricGroups.length}`} />
      </div>
    </div>
  )
}
