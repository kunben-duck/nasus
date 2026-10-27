import type { ProjectRouteContext } from '../ProjectRouteTypes'
import type { RunCardView } from '../ProjectSectionViewModels'
import { runsSectionModel } from '../ProjectSectionViewModels'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function RunsSection({ context, runId }: { context: ProjectRouteContext; runId?: string }) {
  const { t, tx } = useI18n()
  const { runs, selected } = runsSectionModel(context, runId)

  return (
    <>
      <div className="agent-heading">
        <h1>{t('Runs')}</h1>
        <div className="segmented">
          <button className="active">{t('Active')}</button>
          <button>{t('History')}</button>
          <button>{t('Failed')}</button>
        </div>
      </div>
      <div className="quality-asset-panel">
        <div className="quality-panel-header">
          <div>
            <span className="eyebrow">{t('Selected run')}</span>
            <strong>{selected ? tx(selected.title) : t('No run selected')}</strong>
            <p>{selected ? tx(selected.summary) : t('Execution evidence appears here after the quality loop starts runs.')}</p>
          </div>
          {selected ? <span className={`run-status-pill ${selected.status}`}>{tx(selected.status)}</span> : null}
        </div>
        <div className="quality-lane-grid">
          {runs.map((run) => (
            <RunCard run={run} key={run.id} />
          ))}
        </div>
      </div>
    </>
  )
}

function RunCard({ run }: { run: RunCardView }) {
  const { tx } = useI18n()
  return (
    <div className={`quality-lane-card ${run.status}`}>
      <div>
        <span className="quality-lane-dot" />
        <strong>{tx(run.title)}</strong>
      </div>
      <p>{tx(run.summary)}</p>
      <span>{tx(run.status)} · {tx(run.channel)}</span>
    </div>
  )
}
