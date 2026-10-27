import { useId } from 'react'
import type { BuildReviewHandoff } from '../../../../../domains/system-image/buildReviewHandoff'
import { useBuildCompletion } from '../../../../../domains/system-image/useBuildCompletion'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { BuildGapOwnershipPanel } from './BuildGapOwnershipPanel'

export function BuildCompletionPanel({ review }: { review: BuildReviewHandoff }) {
  const { t, tx } = useI18n(), titleId = useId()
  const state = useBuildCompletion(review, titleId)
  const report = state.observation?.report
  const busy = state.sending || state.checking
  return <section className="image-revision-status build-completion-panel" aria-labelledby={titleId}>
    <div className="image-row-heading"><strong id={titleId}>{t('Build completion conditions')}</strong>
      <button type="button" disabled={busy || state.inaccessible && !state.started}
        onClick={state.started ? state.reload : state.assess}>
        {state.started ? t('Reload completion assessment') : t('Verify completion conditions')}
      </button></div>
    <p>{t('This checks every archived source file, member evidence and actual build analysis. It does not index code, call a model, complete the goal or publish the image.')}</p>
    {busy && <p role="status">{t('Verifying the original build and all archived source bytes...')}</p>}
    {(state.inaccessible || state.unacknowledged) && <p role="alert">
      {t('The original assessment could not be verified. Previous results are hidden. Reload only checks the original command; no new assessment is sent.')}
    </p>}
    {state.observation && !report && <p role="status">{['pending', 'running'].includes(state.observation.command.status)
      ? t('The original completion assessment is still running.')
      : t('The original assessment stopped without a verified report. It was not restarted.')}</p>}
    {report && <div data-testid="build-completion-report">
      <p className="build-completion-blocked"><strong>{t('Candidate delivery is blocked')}</strong></p>
      <p>{t('The candidate has not been delivered. Knowledge publication, business approval and real test execution are separate decisions.')}</p>
      <dl className="build-completion-metrics">
        <div><dt>{t('Verified source files')}</dt><dd>{report.source_scans.reduce((total, scan) => total + scan.verified_file_count, 0)}</dd></div>
        <div><dt>{t('Verified source bytes')}</dt><dd>{report.source_scans.reduce((total, scan) => total + scan.verified_byte_count, 0)}</dd></div>
        <div><dt>{t('Verified member evidence')}</dt><dd>{report.readiness.structure.verified_evidence_count}</dd></div>
        <div><dt>{t('Analyses from the actual build')}</dt><dd>{report.code_analyses.filter((analysis) => analysis.build_lineage_verified).length}</dd></div>
      </dl>
      <div className="image-source-document"><dl>
        <div><dt>{t('Original assessment command')}</dt><dd>{state.observation!.command.id}</dd></div>
        <div><dt>{t('Model calls recorded by the goal')}</dt><dd>{report.budget.goal_model_calls_used}</dd></div>
        <div><dt>{t('Recorded active runtime')}</dt><dd>{report.budget.goal_active_runtime_ms === null
          ? t('Not verified') : t('{milliseconds} ms', { milliseconds: report.budget.goal_active_runtime_ms })}</dd></div>
        <div><dt>{t('Full-plan spend and critical conflicts')}</dt><dd>{t('Not verified; unknown is not zero.')}</dd></div>
      </dl></div>
      <details><summary>{t('Actual build analyses and index attempts')}</summary>
        <ul className="link-candidate-list">{report.build_lineages.flatMap((lineage) => lineage.analyses.map((analysis) =>
          <li key={`${lineage.invocation_id}:${analysis.source_revision_id}`}>
            <strong>{t('Original command')}: <code>{lineage.invocation_id}</code></strong>
            <p>{t('Analysis ID')}: <code>{analysis.analysis_id}</code></p>
            <p>{analysis.native ? t('Consumed native index') : t('No native index output was consumed')}
              {analysis.native && <>: <code>{analysis.native.generation.generation_id}</code></>}</p>
            <p>{t('Unused index attempts')}: {analysis.unused_native_generations.length}</p>
          </li>))}</ul>
        {!report.build_lineages.length && <p>{t('No actual build lineage is available for this historical candidate.')}</p>}
      </details>
      <h3>{t('Candidate delivery blockers')}</h3>
      <ul className="build-completion-blockers">{report.blockers.map((code) => <li key={code}><code>{code}</code></li>)}</ul>
      <details><summary>{t('All gaps and required next actions')}</summary>
        <ul className="link-candidate-list">{report.gaps.map((gap, index) => <li key={`${gap.code}:${index}`}>
          <strong><code>{gap.code}</code></strong><p>{tx(gap.reason)}</p><p>{tx(gap.required_action)}</p>
          <p>{t('Owner not assigned')}</p>
        </li>)}</ul>
      </details>
      <BuildGapOwnershipPanel review={review} completion={state.observation!} />
    </div>}
  </section>
}
