import type { LinkCandidatePage } from '../../../../../../domains/system-image/linkCandidateApi'
import type { ImageReadScope } from '../../../../../../domains/system-image/useImageRevisions'
import type { SemanticEvaluationController } from '../../../../../../domains/system-image/useSemanticEvaluation'
import { useI18n } from '../../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../../analysis/AnalysisPagination'
import { SemanticEvaluationResult } from './SemanticEvaluationResult'
import './semantic-evaluation.css'

export function SemanticEvaluationPanel({ scope, page, state }: {
  scope: ImageReadScope; page: LinkCandidatePage; state: SemanticEvaluationController
}) {
  const { t } = useI18n()
  const preview = state.preview.isSuccess ? state.preview.data.preview : undefined
  const history = !state.history.isFetching && !state.history.isError ? state.history.data : undefined
  const modelAvailable = state.choices.some((model) => model.config_id === state.model)
  return <section className="semantic-evaluation-panel" aria-label={t('Semantic evaluation')}>
    <header><h4>{t('Semantic evaluation')}</h4><span>{t('Proposed inference only')}</span></header>
    <p>{t('Select up to 30 candidates and a tested model. A project administrator must explicitly approve sending these source excerpts.')}</p>
    <p>{t('Selected candidates: {count}', { count: state.subjects.length })}</p>
    <label className="semantic-model-choice">{t('Evaluation model')}<select value={state.model} disabled={state.busy || state.models.isFetching}
      onChange={(event) => state.chooseModel(event.target.value)}>
      <option value="">{t('Choose a tested chat model')}</option>
      {state.choices.map((model) => <option key={model.config_id} value={model.config_id}>{model.display_name}</option>)}
    </select></label>
    {state.models.isError && <p role="alert">{t('Model choices are unavailable. Reopen this view to check access.')}</p>}
    {!state.models.isPending && !state.models.isFetching && !state.models.isError && state.choices.length === 0 &&
      <p>{t('No eligible models. Add and test a custom LLM in Model configuration; legacy models must be retested.')}</p>}
    <button className="small-btn" disabled={state.busy || !state.subjects.length || !modelAvailable}
      onClick={state.prepare}>{t('Preview model egress')}</button>
    {state.preview.isPending && <p role="status">{t('Preparing pinned source consent...')}</p>}
    {state.preview.isError && <p role="alert">{t('Preview failed. Check administrator permission, source access and the tested model.')}</p>}
    {preview && <section className="semantic-consent" aria-label={t('Model egress consent')}>
      <p>{t('No source has been sent by this preview.')}</p>
      <dl><dt>{t('Destination')}</dt><dd>{preview.destination}</dd>
        <dt>{t('Pinned model')}</dt><dd>{preview.provider} / {preview.model_name}</dd>
        <dt>{t('Source scope')}</dt><dd>{preview.source_binding_ids.map((id) => <code key={id}>{id}</code>)}</dd>
        <dt>{t('Input size')}</dt><dd>{preview.input_bytes} {t('bytes')}</dd>
        <dt>{t('Call limits')}</dt><dd>{t('One model call, 60 seconds, at most 8192 output tokens. No automatic retry or fallback.')}</dd>
      </dl>
      <p>{t('Provider charges are not estimated. Token limits are not a monetary spending cap.')}</p>
      {state.reviewBlocked && <p role="alert">{t('Historical review blocks evaluation. Inspect the original evaluation and record an explicit human re-review; creating a new image does not clear a rejection.')}</p>}
      {preview.review_screening.some((item) => item.status === 'stale_requires_review') &&
        <p role="status">{t('Source revisions changed. Historical decisions require revalidation; no approval is inherited.')}</p>}
      {!!preview.review_screening.length && <details><summary>{t('Matched historical reviews')}</summary>
        {preview.review_screening.map((item) => <dl key={item.head_decision_id}>
          <dt>{t('Pinned revision')}</dt><dd>{item.source_image_revision_id}</dd>
          <dt>{t('Review decision')}</dt><dd>{item.decision === 'reject' ? t('Rejected relation') : item.decision === 'accept' ? t('Accepted relation') : t('Deferred relation')}</dd>
          <dt>{t('Decision ID')}</dt><dd>{item.head_decision_id}</dd>
        </dl>)}
      </details>}
      <details><summary>{t('Inspect consent pins')}</summary><dl>
        <dt>{t('Pinned revision')}</dt><dd>{preview.request.image_revision_id}</dd>
        <dt>{t('Input digest')}</dt><dd>{preview.request.input_digest}</dd>
        <dt>{t('Model configuration digest')}</dt><dd>{preview.request.model_config_digest}</dd>
        <dt>{t('Review scope digest')}</dt><dd>{preview.request.review_scope_digest}</dd>
      </dl></details>
      <label className="semantic-confirm"><input type="checkbox" checked={state.confirmed}
        disabled={state.busy || state.reviewBlocked || !modelAvailable || !state.execution.isIdle} onChange={(event) => state.setConfirmed(event.target.checked)} />
        {t('I authorize one call to this destination with these selected source excerpts. This does not approve a relation or coverage.')}</label>
      <button className="small-btn primary" onClick={state.execute} disabled={state.busy || state.reviewBlocked || !modelAvailable || !state.confirmed || !state.execution.isIdle}>
        {t('Confirm and evaluate')}</button>
    </section>}
    {state.execution.isPending && <p role="status">{t('Evaluating selected evidence. Leaving this view does not cancel the confirmed call.')}</p>}
    {state.execution.isError && <p role="alert">{t('The call did not return a committed result. Reload evaluation history before creating a new preview; this call will not be retried automatically.')}</p>}
    <section className="semantic-history" aria-label={t('Evaluation history')}>
      <header><h4>{t('Evaluation history')}</h4><button className="small-btn" disabled={state.busy || state.history.isFetching}
        onClick={state.refreshHistory}>{t('Reload evaluation history')}</button></header>
      {state.history.isFetching && <p role="status">{t('Checking source access...')}</p>}
      {history?.items.length === 0 && <p>{t('No saved evaluations for this target and relation.')}</p>}
      {history?.items.map((item) => <article key={item.invocation_id}>
        <div><strong>{item.model_name}</strong><time>{item.recorded_at}</time><code>{item.invocation_id}</code></div>
        {item.state === 'archived' ? <button className="small-btn" onClick={() => state.inspect(item)} disabled={state.busy}>
          {t('Inspect evaluation')}</button> : <span>{t('No committed result. The call may be running or interrupted.')}</span>}
      </article>)}
      {history && <AnalysisPagination label={t('Evaluation history pages')} page={state.historyPage} previous={state.previous} next={state.next} />}
    </section>
    {state.selected && (state.result.isPending || state.result.isFetching) && <p role="status">{t('Verifying archived evaluation...')}</p>}
    {state.selected && !state.result.isError && !state.result.isFetching && state.result.data &&
      <SemanticEvaluationResult key={state.result.data.invocation_id} scope={scope} page={page} result={state.result.data} />}
  </section>
}
