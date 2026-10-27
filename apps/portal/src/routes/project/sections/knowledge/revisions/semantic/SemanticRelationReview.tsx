import type { ImageReadScope } from '../../../../../../domains/system-image/useImageRevisions'
import type { SemanticJudgment, SemanticResult } from '../../../../../../domains/system-image/types/semanticEvaluation'
import type { SemanticReviewChoice } from '../../../../../../domains/system-image/types/semanticReview'
import { useSemanticReview } from '../../../../../../domains/system-image/useSemanticReview'
import { useI18n } from '../../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../../analysis/AnalysisPagination'
import { SemanticReviewFreeze } from './SemanticReviewFreeze'

export function SemanticRelationReview({ scope, result, subject }: {
  scope: ImageReadScope; result: SemanticResult; subject: SemanticJudgment
}) {
  const { t } = useI18n()
  const state = useSemanticReview(scope, result, subject)
  const labels = { accept: t('Accepted relation'), reject: t('Rejected relation'), defer: t('Deferred relation') }
  const page = state.page
  return <section className="semantic-review" aria-label={t('Semantic relation review')}>
    <header><h5>{t('Semantic relation review')}</h5><button className="small-btn" disabled={state.query.isFetching || state.write.isPending}
      onClick={state.reload}>{t('Reload review history')}</button></header>
    <p>{t('Review this exact endpoint pair. Repeating model evaluation does not reset earlier human decisions.')}</p>
    <p>{t('Accepting a relation does not approve its business oracle, prove test coverage or publish an image. Freezing membership requires separate confirmation.')}</p>
    {state.query.isFetching && <p role="status">{t('Checking source access...')}</p>}
    {state.write.isPending && <p role="status">{t('Recording semantic review...')}</p>}
    {state.write.isSuccess && <p role="status">{t('Review recorded. The source authority remains pending confirmation.')}</p>}
    {state.write.isError && <p role="alert">{state.stale
      ? t('Another reviewer changed this claim. Reload its history and explicitly confirm a new decision.')
      : t('Review was not acknowledged. Check permission and reload history before retrying; no automatic retry was sent.')}</p>}
    {page && <>
      <div className="semantic-review-head"><strong>{page.head ? labels[page.head.decision] : t('Not reviewed')}</strong>
        {page.head && <><p>{page.head.reason}</p><small>{page.head.reviewer_actor} · <time>{page.head.recorded_at}</time></small>
          <p>{t('Evaluation ID')}: <code>{page.head.evaluation_id}</code></p></>}
      </div>
      <details><summary>{t('Inspect review pins')}</summary><dl>
        <dt>{t('Assertion ID')}</dt><dd>{page.assertion.assertion_id}</dd>
        <dt>{t('Assertion digest')}</dt><dd>{page.assertion.assertion_digest}</dd>
        <dt>{t('Evidence digest')}</dt><dd>{page.assertion.evidence_digest}</dd>
        <dt>{t('Decision ID')}</dt><dd>{page.head_decision_id ?? t('Not reviewed')}</dd>
      </dl></details>
      {!page.assertion.can_accept && <p>{t('This evaluation does not support acceptance. Reject or defer it until grounded supporting evidence is available.')}</p>}
      <fieldset disabled={state.write.isPending || !state.write.isIdle}>
        <legend>{t('Review decision')}</legend>
        <label>{t('Review decision')}<select value={state.decision} onChange={(event) => state.choose(event.target.value as SemanticReviewChoice)}>
          <option value="defer">{t('Defer relation')}</option><option value="reject">{t('Reject relation')}</option>
          <option value="accept" disabled={!page.assertion.can_accept}>{t('Accept relation')}</option>
        </select></label>
        <label>{t('Review reason')}<textarea value={state.reason} maxLength={2000} rows={3} onChange={(event) => state.explain(event.target.value)} /></label>
        <label className="semantic-confirm"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
          {t('Confirm this decision for these exact revisions. This does not approve coverage or publication.')}</label>
        <button className="small-btn primary" disabled={!state.canSubmit} onClick={state.submit}>{t('Record review')}</button>
      </fieldset>
      {page.head && !state.write.isPending && <SemanticReviewFreeze key={`${page.head_decision_id}:${state.query.dataUpdatedAt}`} page={page} />}
      <details className="semantic-review-history"><summary>{t('Review history: {count} decisions', { count: page.total })}</summary>
        {page.items.map((item) => <article key={item.decision_id}><strong>{labels[item.decision]}</strong>
          <p>{item.reason}</p><small>{item.reviewer_actor} · <time>{item.recorded_at}</time></small>
          <p>{t('Evaluation ID')}: <code>{item.evaluation_id}</code></p></article>)}
        <AnalysisPagination label={t('Review history pages')} page={state.pageNumber} previous={state.previous} next={state.next} />
      </details>
    </>}
  </section>
}
