import type { ProjectRouteContext } from '../ProjectRouteTypes'
import { MetricCard } from './primitives/MetricCards'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ReleaseReadinessSection({ context }: { context: ProjectRouteContext }) {
  const { t, tx } = useI18n()
  const state = context.workspace?.quality_loop_state
  const readiness = context.releaseReadiness
  const blocked = Boolean(readiness?.blockers || readiness?.evidence_summary.quality_assessment_unknown)

  return (
    <>
      <div className="agent-heading">
        <h1>{t('Release Readiness')}</h1>
        <div className="segmented">
          <button className="active">{t('Score')}</button>
          <button>{t('Evidence')}</button>
          <button>{t('Gate')}</button>
        </div>
      </div>
      <div className="metric-grid">
        <MetricCard label={t('Status')} value={tx(blocked ? 'blocked' : state?.status ?? 'not started')} />
        <MetricCard label={t('Score')} value={readiness ? `${readiness.score}` : t('Unknown')} />
        <MetricCard label={t('Blockers')} value={`${state?.blockers.length ?? 0}`} />
        <MetricCard label={t('Approvals')} value={`${context.workspace?.approvals.length ?? 0}`} />
      </div>
      {readiness?.score_breakdown ? (
        <div className="metric-grid release-score-breakdown">
          <MetricCard label={t('Execution')} value={`${readiness.score_breakdown.execution ?? 0}/35`} />
          <MetricCard label={t('Quality assets')} value={`${readiness.score_breakdown.quality_assets ?? 0}/25`} />
          <MetricCard label={t('System context')} value={`${readiness.score_breakdown.system_context ?? 0}/20`} />
          <MetricCard label={t('Governance')} value={`${readiness.score_breakdown.governance ?? 0}/20`} />
        </div>
      ) : null}
      <div className="quality-asset-panel">
        <div className="quality-panel-header">
          <div>
            <span className="eyebrow">{t('Release gate')}</span>
            <strong>{state?.label ? tx(state.label) : t('Quality loop is not ready for release yet')}</strong>
            <p>{readiness?.summary ? tx(readiness.summary) : t('Nasus will score release readiness from evidence, failures, approvals, and system image freshness.')}</p>
          </div>
          <button className="composer-action-button build-submit-button" onClick={() => context.invokeProjectAction('release.assess')} disabled={context.loading}>
            {t('Assess release')}
          </button>
        </div>
        {state?.blockers.length ? (
          <div className="quality-blocker-list">
            {state.blockers.map((blocker) => <span key={blocker}>{tx(blocker)}</span>)}
          </div>
        ) : null}
      </div>
    </>
  )
}
