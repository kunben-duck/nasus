import type { IndexGeneration } from '../../../../domains/system-image/types/frozenIndex'
import { useContextRetrievalPlan } from '../../../../domains/system-image/useContextRetrievalPlan'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { ContextRetrievalExecutionPanel } from './ContextRetrievalExecutionPanel'

export function ContextRetrievalPlanPanel({ generation }: { generation: IndexGeneration }) {
  const { t } = useI18n(), state = useContextRetrievalPlan(generation), plan = state.view
  return <section className="frozen-index-preview" aria-label={t('Context retrieval query plan')}>
    <div className="frozen-index-heading"><h3>{t('Context retrieval query plan')}</h3>
      <button type="button" className="small-btn" onClick={state.inspect} disabled={state.preview.isFetching}>{t('Preview AC query budget')}</button></div>
    <p>{t('Prepare one query per frozen AC using its own requirement description. This preview sends nothing to a model.')}</p>
    {state.open && state.preview.isFetching && <p role="status">{t('Verifying every AC, source evidence and the pinned index...')}</p>}
    {state.open && state.preview.isError && <p role="alert">{t('Query plan could not be verified. Previous content is hidden. Check the current publication, model, source access and input limits.')}</p>}
    {plan && <div data-testid="context-retrieval-plan">
      {plan.state === 'missing_requirements' ? <p role="status">{t('No source ACs in this publication. No queries or model calls are planned.')}</p> : <dl>
        <div><dt>{t('Frozen input')}</dt><dd>{t('{queries} AC queries · {sources} sources · {bytes} UTF-8 bytes', {
          queries: plan.query_count, sources: plan.source_binding_ids.length, bytes: plan.input_bytes })}</dd></div>
        <div><dt>{t('Model call budget')}</dt><dd>{t('Up to {calls} native batches of {size} queries, {seconds}s per call. This is not a fee or token estimate.', {
          calls: plan.max_model_calls, size: plan.batch_size, seconds: plan.timeout_per_call_seconds })}</dd></div>
        <div><dt>{t('Destination')}</dt><dd>{plan.model.base_url}<br />{plan.model.model_name}</dd></div>
      </dl>}
      <details><summary>{t('Query plan and model digests')}</summary><code>{plan.plan_digest}</code><code>{plan.queries_digest}</code><code>{plan.model.config_digest}</code></details>
      <p>{t('Preview only. No queries were sent and no generation authorization was created.')}</p>
      {plan.execution_available && plan.query_count > 0 && <ContextRetrievalExecutionPanel key={`${plan.plan_digest}:${state.preview.dataUpdatedAt}`} plan={plan} />}
    </div>}
  </section>
}
