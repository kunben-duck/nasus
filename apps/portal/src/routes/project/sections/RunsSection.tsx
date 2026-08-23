import type { ProjectRouteContext } from '../ProjectRouteTypes'
import type { RunCardView } from '../ProjectSectionViewModels'
import { runsSectionModel } from '../ProjectSectionViewModels'

export function RunsSection({ context, runId }: { context: ProjectRouteContext; runId?: string }) {
  const { runs, selected } = runsSectionModel(context, runId)

  return (
    <>
      <div className="agent-heading">
        <h1>Runs</h1>
        <div className="segmented">
          <button className="active">Active</button>
          <button>History</button>
          <button>Failed</button>
        </div>
      </div>
      <div className="quality-asset-panel">
        <div className="quality-panel-header">
          <div>
            <span className="eyebrow">Selected run</span>
            <strong>{selected?.title ?? 'No run selected'}</strong>
            <p>{selected?.summary ?? 'Execution evidence appears here after the quality loop starts runs.'}</p>
          </div>
          {selected ? <span className={`run-status-pill ${selected.status}`}>{selected.status}</span> : null}
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
  return (
    <div className={`quality-lane-card ${run.status}`}>
      <div>
        <span className="quality-lane-dot" />
        <strong>{run.title}</strong>
      </div>
      <p>{run.summary}</p>
      <span>{run.status} · {run.channel}</span>
    </div>
  )
}
