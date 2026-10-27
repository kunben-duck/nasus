import type { PublicationPin } from '../../../../domains/system-image/types/frozenIndex'
import { useFrozenIndex } from '../../../../domains/system-image/useFrozenIndex'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { ContextRetrievalPlanPanel } from './ContextRetrievalPlanPanel'
import './evidence-inspector.css'
import './frozen-index.css'

export function FrozenIndexPanel({ projectId, pin }: { projectId: string; pin: PublicationPin }) {
  const { t } = useI18n(), state = useFrozenIndex(projectId, pin)
  const view = state.view, generation = view?.generation, preview = state.prepared?.preview
  return <section className="frozen-index-panel" aria-label={t('Published retrieval index')}>
    <div className="frozen-index-heading">
      <div><strong>{t('Published retrieval index')}</strong><p>{t('Search the exact published code, requirements and tests. Similarity is not coverage or approval.')}</p></div>
      <button type="button" className="small-btn" aria-expanded={state.open} onClick={state.toggle} disabled={state.busy}>{t('Inspect retrieval index')}</button>
    </div>
    {state.open && <>
      <div className="frozen-index-actions"><button type="button" className="small-btn" disabled={state.busy || state.status.isFetching || state.models.isFetching}
        onClick={state.reload}>{t('Reload index status')}</button></div>
      {state.status.isFetching && <p role="status">{t('Verifying index, publication and source access...')}</p>}
      {state.status.isError && <p role="alert">{t('Index scope could not be verified. Previous content is hidden; reload the knowledge page to check the current head and access.')}</p>}
      {view && <>
        <p role="status" data-testid="frozen-index-state">{t(view.state === 'ready' ? 'Index ready for this publication'
          : view.state === 'rebuild_required' ? 'Model configuration changed. A new preview and confirmed build are required.' : 'No completed index for this publication.')}</p>
        <details className="frozen-index-pins"><summary>{t('Publication and index pins')}</summary>
          <code>{pin.publication_id}</code><code>{pin.image_artifact_hash}</code>
          {generation && <><code>{generation.generation_id}</code><code>{generation.artifact_hash}</code><code>{generation.model.config_digest}</code></>}
        </details>
        {generation && <p>{t('{count} indexed chunks · {dimensions} dimensions', { count: generation.document_count, dimensions: generation.dimensions })}
          <br />{generation.model.model_name} · {generation.model.base_url}</p>}
        {generation && view.state === 'ready' && view.can_build && <ContextRetrievalPlanPanel key={generation.generation_id} generation={generation} />}
        {!view.can_build ? <p>{t('Only a project administrator can authorize index model egress.')}</p> : <>
          <div className="frozen-index-actions"><label>{t('Index embedding model')}
            <select value={state.modelId} disabled={state.busy || state.models.isFetching} onChange={(event) => state.choose(event.target.value)}>
              <option value="">{t('Select a tested embedding model')}</option>
              {state.choices.map((model) => <option key={model.config_id} value={model.config_id}>{model.display_name}</option>)}
            </select></label>
            <button type="button" className="small-btn" disabled={!state.canPreview} onClick={state.prepare}>{t('Preview index egress')}</button>
          </div>
          {state.models.isFetching && <p role="status">{t('Checking tested embedding models...')}</p>}
          {state.models.isError && <p role="alert">{t('Embedding models could not be loaded. No fallback model will be selected.')}</p>}
          {!state.models.isFetching && !state.models.isError && !state.choices.length && <p>{t('Add and test an OpenAI-compatible embedding model in Model configuration first. System default and legacy imports are not eligible.')}</p>}
          {state.preview.isPending && <p role="status">{t('Reading complete frozen evidence. This preview does not call a model.')}</p>}
          {state.preview.isError && <p role="alert">{t('Index preview could not be verified. Reload and check the model, source access and current publication.')}</p>}
          {preview && <div className="frozen-index-preview" data-testid="frozen-index-preview">
            <h3>{t('Review model egress')}</h3>
            <dl><div><dt>{t('Destination')}</dt><dd>{preview.model.base_url}</dd></div>
              <div><dt>{t('Model')}</dt><dd>{preview.model.model_name}</dd></div>
              <div><dt>{t('Frozen input')}</dt><dd>{t('{sources} sources · {chunks} chunks · {bytes} UTF-8 bytes', {
                sources: preview.source_binding_ids.length, chunks: preview.document_count, bytes: preview.input_bytes })}</dd></div>
              <div><dt>{t('Model call budget')}</dt><dd>{t('At most {calls} batches, {size} chunks each, {seconds}s per call. Fees are not estimated.', {
                calls: preview.max_model_calls, size: preview.batch_size, seconds: preview.timeout_per_call_seconds })}</dd></div></dl>
            <details><summary>{t('Exact input and model digests')}</summary><code>{preview.request.input_digest}</code><code>{preview.model.config_digest}</code>
              {preview.source_binding_ids.map((binding) => <code key={binding}>{binding}</code>)}</details>
            <p>{t('This sends frozen source text and later project retrieval queries to the pinned embedding destination. It does not authorize rerank, chat source export, test generation or release.')}</p>
            <label className="frozen-index-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.write.isIdle}
              onChange={(event) => state.confirm(event.target.checked)} />{t('I authorize these exact source bytes, model destination and subsequent retrieval queries.')}</label>
            <button type="button" className="small-btn primary" disabled={!state.canBuild} onClick={state.build}>{t('Build confirmed index')}</button>
          </div>}
        </>}
      </>}
      {state.write.isPending && <p role="status">{t('Building the confirmed index. No partial generation is searchable; do not submit another build.')}</p>}
      {state.write.isError && <p role="alert">{t('Build completion was not acknowledged. Reload index status before making a new decision. No automatic retry was sent.')}</p>}
      {state.write.isSuccess && <p role="status">{t('Index committed. Publication and business authority were not changed.')}</p>}
    </>}
  </section>
}
