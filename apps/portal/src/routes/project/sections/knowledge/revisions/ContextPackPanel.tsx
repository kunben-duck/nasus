import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useContextPacks } from '../../../../../domains/system-image/useContextPacks'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { ContextPackDetails } from './ContextPackDetails'
import { TestDesignScopePanel } from '../scope/TestDesignScopePanel'
import '../evidence-inspector.css'
import './context-packs.css'

export function ContextPackPanel({ scope, revisionId, imageHash, publicationId, retrievalBindings }: {
  scope: ImageReadScope; revisionId: string; imageHash: string; publicationId?: string; retrievalBindings?: Record<string, string>
}) {
  const { t } = useI18n()
  const state = useContextPacks(scope, { project_id: scope.projectId, image_revision_id: revisionId, image_artifact_hash: imageHash }, publicationId, retrievalBindings)
  const historical = state.archived
  return <section className="context-pack-panel" aria-label={t('Test-design context packs')}>
    <button type="button" className="small-btn" aria-expanded={state.open} onClick={state.toggle} disabled={state.write.isPending}>{t(publicationId ? 'Inspect published context' : 'Inspect test-design context')}</button>
    {state.open && <>
      <p>{t('Pin source requirements, approved oracles and retrieval evidence. Draft investigation only, not permission to generate, execute or release.')}</p>
      <div className="context-pack-controls"><label>{t('Context budget ceiling')}<input type="number" min={512} max={32768} step={1}
        value={state.budget} disabled={state.write.isPending} onChange={(event) => state.editBudget(event.target.value)} /></label>
        <button type="button" className="small-btn" disabled={!state.canPreview} onClick={state.inspect}>{t('Preview context')}</button>
        <button type="button" className="small-btn" disabled={state.write.isPending || state.history.isFetching || state.archive.isFetching} onClick={state.reload}>{t('Reload context history')}</button>
      </div>
      {(state.preview.isFetching || state.archive.isFetching) && <p role="status">{t('Verifying context and source access...')}</p>}
      {state.overBudget && <p role="alert">{t('Mandatory context exceeds the budget. Increase it or split the scope; no requirement was discarded.')}</p>}
      {state.write.isPending && <p role="status">{t('Archiving fixed context...')}</p>}
      {state.write.isError && <p role="alert">{state.stale ? t('Context inputs changed. Preview and confirm again.') : t('Archive was not acknowledged. Check history before retrying; no automatic retry was sent.')}</p>}
      {state.view && <>
        <ContextPackDetails key={state.view.input_digest} scope={scope} context={state.view.context} />
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.write.isPending || !state.write.isIdle}
          onChange={(event) => state.confirm(event.target.checked)} />{t('I confirm archiving these exact inputs and gaps. This is not generation or execution approval.')}</label>
        <button type="button" className="small-btn primary" disabled={!state.canSave} onClick={state.save}>{t('Archive context')}</button>
      </>}
      {state.selected && historical && <section className="context-pack-archive" aria-label={t('Archived context')}>
        <strong>{t('Immutable historical context')}</strong><code>{historical.metadata.context_id}</code>
        <p role="status">{historical.current_use.stale ? t('Inputs have changed. This historical pack cannot authorize current generation.') : t('Inputs unchanged. This draft still does not authorize generation.')}</p>
        {historical.current_use.reason === 'source_change_invalidated' && <p data-testid="context-invalidation">
          {t('Source changes invalidated current use of this image. Historical contents remain unchanged.')}
          <code>{historical.current_use.invalidation_id}</code>
        </p>}
        <ContextPackDetails key={historical.metadata.content_hash} scope={scope} context={historical.context} />
        <TestDesignScopePanel key={historical.metadata.context_id} scope={scope} context={historical} />
      </section>}
      <h3>{t('Context archive history')}</h3>
      {state.history.isFetching ? <p role="status">{t('Checking source access...')}</p> : state.history.data && <>
        {!state.history.data.items.length && <p>{t('No archived context for this image.')}</p>}
        <ul className="context-history-list">{state.history.data.items.map((item) => <li key={item.context_id}>
          <button type="button" className="small-btn" disabled={state.write.isPending} aria-pressed={state.selected === item.context_id} onClick={() => state.choose(item.context_id)}>
            <time>{item.recorded_at}</time><code>{item.context_id}</code>
          </button>
        </li>)}</ul>
        <AnalysisPagination label={t('Context history pages')} page={state.page} previous={state.previous} next={state.next} />
      </>}
    </>}
  </section>
}
