import type { ProjectCard } from '../../../domains/platform/types'
import type { SystemImageData } from '../../../domains/system-image/types'

export function RunSettingsPanel({ project, systemImage }: { project?: ProjectCard; systemImage?: SystemImageData }) {
  const codeSource = systemImage?.sources.find((source) => source.source_type === 'code')
  const usSource = systemImage?.sources.find((source) => source.source_type === 'us_doc')
  const testSource = systemImage?.sources.find((source) => source.source_type === 'test_asset')

  return (
    <aside className="run-panel">
      <div className="run-panel-header">
        <span>Run settings</span>
        <button>⌘ Get code</button>
        <button>×</button>
      </div>
      <div className="settings-card featured">
        <strong>Nasus Quality Agent</strong>
        <span>agent-first-quality-v1</span>
        <p>Autonomous quality agent running on the project tool catalog and governed workflow gates.</p>
      </div>
      <div className="settings-card">
        <strong>System instructions</strong>
        <p>Use system image evidence, cite source refs, and never write official baseline without approval.</p>
      </div>
      <div className="panel-section">
        <div className="panel-section-title">Tools</div>
        <ToggleRow label="Code analysis" active={codeSource?.ingestion_status === 'indexed'} />
        <ToggleRow label="US document parser" active={usSource?.ingestion_status === 'indexed'} />
        <ToggleRow label="Test asset ingestion" active={testSource?.ingestion_status === 'indexed'} />
        <ToggleRow label="Release gate" active={false} />
      </div>
      <div className="panel-section">
        <div className="panel-section-title">Project</div>
        <p className="panel-copy">{project?.name ?? 'No project selected'} · System image {project?.system_image_status ?? 'draft'}</p>
      </div>
      <div className="panel-section">
        <div className="panel-section-title">Quality metrics</div>
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
