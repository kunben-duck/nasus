import type { ProjectCard } from '../../../domains/platform/types'
import type { SystemImageData } from '../../../domains/system-image/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function RunSettingsPanel({ project, systemImage }: { project?: ProjectCard; systemImage?: SystemImageData }) {
  const { t, tx } = useI18n()
  const codeSource = systemImage?.sources.find((source) => source.source_type === 'code')
  const usSource = systemImage?.sources.find((source) => source.source_type === 'us_doc')
  const testSource = systemImage?.sources.find((source) => source.source_type === 'test_asset')

  return (
    <aside className="run-panel">
      <div className="run-panel-header">
        <span>{t('Run settings')}</span>
        <button>⌘ {t('Get code')}</button>
        <button>×</button>
      </div>
      <div className="settings-card featured">
        <strong>{t('Nasus Quality Agent')}</strong>
        <span>agent-first-quality-v1</span>
        <p>{t('Autonomous quality agent running on the project tool catalog and governed workflow gates.')}</p>
      </div>
      <div className="settings-card">
        <strong>{t('System instructions')}</strong>
        <p>{t('Use system image evidence, cite source refs, and never write official baseline without approval.')}</p>
      </div>
      <div className="panel-section">
        <div className="panel-section-title">{t('Tools')}</div>
        <ToggleRow label={t('Code analysis')} active={codeSource?.ingestion_status === 'indexed'} />
        <ToggleRow label={t('US document parser')} active={usSource?.ingestion_status === 'indexed'} />
        <ToggleRow label={t('Test asset ingestion')} active={testSource?.ingestion_status === 'indexed'} />
        <ToggleRow label={t('Release gate')} active={false} />
      </div>
      <div className="panel-section">
        <div className="panel-section-title">{t('Project')}</div>
        <p className="panel-copy">{project?.name ?? t('No project selected')} · {t('System image')} {tx(project?.system_image_status ?? 'draft')}</p>
      </div>
      <div className="panel-section">
        <div className="panel-section-title">{t('Quality metrics')}</div>
        {(systemImage?.metric_snapshots ?? []).map((metric) => (
          <div className="metric-row" key={metric.id}>
            <span>{metric.metric_group.replaceAll('_', ' ')}</span>
            <strong>{Object.keys(metric.metrics).length}</strong>
          </div>
        ))}
      </div>
    </aside>
  )
}

function ToggleRow({ label, active }: { label: string; active: boolean | undefined }) {
  return (
    <div className="toggle-row">
      <span>{label}</span>
      <span className={`toggle ${active ? 'on' : ''}`}><i /></span>
    </div>
  )
}
