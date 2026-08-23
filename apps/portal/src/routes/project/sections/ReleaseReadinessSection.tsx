import type { ProjectRouteContext } from '../ProjectRouteTypes'
import { MetricCard } from './primitives/MetricCards'

export function ReleaseReadinessSection({ context }: { context: ProjectRouteContext }) {
  const state = context.workspace?.quality_loop_state
  const decision = context.workspace?.release_decision
  const readiness = context.releaseReadiness

  return (
    <>
      <div className="agent-heading">
        <h1>Release Readiness</h1>
        <div className="segmented">
          <button className="active">Score</button>
          <button>Evidence</button>
          <button>Gate</button>
        </div>
      </div>
      <div className="metric-grid">
        <MetricCard label="Status" value={decision?.status ?? state?.status ?? 'not started'} />
        <MetricCard label="Score" value={`${decision?.score ?? state?.release_score ?? 0}`} />
        <MetricCard label="Blockers" value={`${state?.blockers.length ?? 0}`} />
        <MetricCard label="Approvals" value={`${context.workspace?.approvals.length ?? 0}`} />
      </div>
      {readiness?.score_breakdown ? (
        <div className="metric-grid release-score-breakdown">
          <MetricCard label="Execution" value={`${readiness.score_breakdown.execution ?? 0}/35`} />
          <MetricCard label="Quality assets" value={`${readiness.score_breakdown.quality_assets ?? 0}/25`} />
          <MetricCard label="System context" value={`${readiness.score_breakdown.system_context ?? 0}/20`} />
          <MetricCard label="Governance" value={`${readiness.score_breakdown.governance ?? 0}/20`} />
        </div>
      ) : null}
      <div className="quality-asset-panel">
        <div className="quality-panel-header">
          <div>
            <span className="eyebrow">Release gate</span>
            <strong>{state?.label ?? 'Quality loop is not ready for release yet'}</strong>
            <p>{decision?.rationale ?? 'Nasus will score release readiness from evidence, failures, approvals, and system image freshness.'}</p>
          </div>
          <button className="composer-action-button build-submit-button" onClick={() => context.invokeProjectAction('release.assess')} disabled={context.loading}>
            Assess release
          </button>
        </div>
        {state?.blockers.length ? (
          <div className="quality-blocker-list">
            {state.blockers.map((blocker) => <span key={blocker}>{blocker}</span>)}
          </div>
        ) : null}
      </div>
    </>
  )
}
