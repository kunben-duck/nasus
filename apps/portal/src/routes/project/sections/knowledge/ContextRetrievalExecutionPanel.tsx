import { useId, useState } from 'react'
import type { ContextRetrievalPlan } from '../../../../domains/system-image/types/contextRetrievalPlan'
import { useContextRetrieval } from '../../../../domains/system-image/useContextRetrieval'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { ContextPackPanel } from './revisions/ContextPackPanel'

export function ContextRetrievalExecutionPanel({ plan }: { plan: ContextRetrievalPlan }) {
  const state = useContextRetrieval(plan), { t } = useI18n(), sessionId = useId()
  const [failed, setFailed] = useState(false)
  if (failed) return <p role="alert">{t('Published context could not be verified. Reload the knowledge page to check the head and source access.')}</p>
  return <section aria-label={t('Execute AC context retrieval')}>
    <p>{t('Confirmed queries run in Temporal. Completed batches resume without repeated model calls. Unknown outcomes require new consent, never automatic resending.')}</p>
    {state.history.isError && <p role="alert">{t('Retrieval history could not be verified. Previous results are hidden.')}</p>}
    <label className="frozen-index-consent"><input type="checkbox" checked={state.consent} disabled={state.busy || !state.write.isIdle || state.history.isError}
      onChange={(event) => state.setConsent(event.target.checked)} />{t('I authorize all these AC queries and this exact embedding destination.')}</label>
    <div className="frozen-index-actions"><button type="button" className="small-btn primary" disabled={!state.ready} onClick={state.start}>{t('Retrieve confirmed AC context')}</button>
      {state.job?.status === 'running' && <button type="button" className="small-btn" disabled={state.cancel.isPending} onClick={state.stop}>{t('Cancel context retrieval')}</button>}
    </div>
    {state.busy && <p role="status">{t('Retrieval is running. No partial AC mapping is available. You can return to this panel after a refresh.')}</p>}
    {(state.write.isError || state.cancel.isError) && <p role="alert">{t('Command acknowledgement was lost or rejected. Status is being checked; no automatic write retry was sent.')}</p>}
    {(state.job?.status === 'failed' || state.job?.status === 'cancelled') && <p role="status">{t('Retrieval stopped without a complete mapping. Preview again before a new attempt.')}</p>}
    {state.result.isFetching && <p role="status">{t('Verifying committed AC mappings and source access...')}</p>}
    {state.result.isError && <p role="alert">{t('Completed retrieval could not be verified. No context can use this response.')}</p>}
    {state.view && <div data-testid="context-retrieval-result">
      <p role="status">{t('{count} AC retrievals committed. Use their fixed traces to preview context; this is not generation or coverage approval.', { count: state.view.query_count })}</p>
      {state.view.batches.some((batch) => batch.fallback) && <p>{t('Embedding was unavailable for some queries. Those traces use lexical retrieval in the same fixed index.')}</p>}
      <code>{state.view.invocation_id}</code>
      <ContextPackPanel key={state.view.invocation_id} scope={{ projectId: plan.request.project_id, sessionId, onFailure: setFailed }}
        revisionId={plan.publication_pin.image_revision_id} imageHash={plan.publication_pin.image_artifact_hash}
        publicationId={plan.request.publication_id} retrievalBindings={state.view.retrieval_bindings} />
    </div>}
  </section>
}
