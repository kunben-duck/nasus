import type { ContextArchive } from '../../../../../domains/system-image/types/contextPack'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useTestDesignScope } from '../../../../../domains/quality-loop/useTestDesignScope'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeContractEditor } from './ScopeContractEditor'
import { ScopeText } from './ScopeInputs'
import { TestDesignGenerationPanel } from './TestDesignGenerationPanel'
import './test-design-scope.css'

export function TestDesignScopePanel({ context, scope }: { context: ContextArchive; scope: ImageReadScope }) {
  const { t, tx } = useI18n(), state = useTestDesignScope(context, scope.sessionId, scope.onFailure)
  const view = state.view, content = state.content
  return <section className="test-design-scope" aria-label={t('Reviewed test-design scope')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.write.isPending} onClick={state.toggle}>{t('Inspect test-design scope')}</button>
    {state.open && <>
      <p>{t('Review exact archived requirements and observable obligations. Scope approval does not authorize test generation, execution or release.')}</p>
      <button type="button" className="small-btn" disabled={state.query.isFetching || state.archive.isFetching || state.write.isPending} onClick={state.reload}>{t('Reload scope history')}</button>
      {(state.query.isFetching || state.archive.isFetching) && <p role="status">{t('Verifying scope history and current source access...')}</p>}
      {state.write.isPending && <p role="status">{t('Recording confirmed scope decision...')}</p>}
      {state.write.isSuccess && <p role="status">{t('Scope decision recorded. Generation remains separately gated.')}<code>{state.write.data}</code></p>}
      {state.write.isError && <p role="alert">{state.stale ? t('Scope inputs or head changed. Reload and confirm a new decision.') : t('Scope decision was not acknowledged. Reload history before retrying; no automatic retry was sent.')}</p>}
      {view && <>
        {!state.mayApprove && <p role="status">{t('A new scope approval requires a current published context with every AC and business rule independently approved.')}</p>}
        {!view.head && <p>{t('No reviewed scope for this context.')}</p>}
        {content && <div className="scope-record" aria-label={t('Recorded scope decision')}>
          <strong>{content.revision.status === 'withdrawn' ? t('Withdrawn scope') : content.current_use.scope_current ? t('Current reviewed scope') : t('Historical scope; not current')}</strong>
          <p>{content.current_use.scope_complete ? t('Reviewed scope has no explicit blockers; generation still needs separate preflight.') : t('Scope is incomplete, withdrawn or stale. It cannot authorize generation.')}</p>
          <code>{content.revision.revision_id}</code><code>{content.revision.invocation_id}</code>
          <small>{content.revision.authority_actor} · <time>{content.revision.recorded_at}</time></small>
          <p>{content.request.reason}</p>
          {!!content.assessment?.blockers.length && <p>{t('{count} explicit scope blockers', { count: content.assessment.blockers.length })}</p>}
          {content.request.contract && <ScopeContractEditor context={context.context} value={content.request.contract} readOnly onChange={() => {}} />}
          <TestDesignGenerationPanel key={content.revision.revision_id} scope={content} sessionId={scope.sessionId} />
        </div>}
        <label>{t('Scope history')}<select value={state.selected} disabled={state.write.isPending} onChange={(event) => state.choose(event.target.value)}>
          <option value="">{t('Current scope head')}</option>{view.history.map((item) => <option value={item.revision_id} key={item.revision_id}>{item.sequence} · {tx(item.status)} · {item.recorded_at}</option>)}
        </select></label>
        {view.can_review ? <div className="scope-actions">
          <button type="button" className="small-btn" disabled={state.write.isPending || !state.mayApprove} onClick={() => state.begin()}>{t('Review scope')}</button>
          <button type="button" className="small-btn" disabled={state.write.isPending || view.head?.revision.status !== 'approved'} onClick={() => state.begin(true)}>{t('Withdraw scope')}</button>
        </div> : <p>{t('Only a project reviewer can review this scope.')}</p>}
        {state.editing && view.can_review && !state.selected && <fieldset className="scope-review-form" disabled={state.write.isPending || !state.write.isIdle}>
          <legend>{t('New scope decision')}</legend>
          {state.draft && <ScopeContractEditor context={context.context} value={state.draft} onChange={state.edit} />}
          <ScopeText label={t('Review reason')} value={state.reason} onChange={state.explain} />
          <p>{t('Complete all assessments, references and examples before recording. Unknown behavior must remain an explicit gap.')}</p>
          <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
            {state.decision === 'withdraw' ? t('I confirm withdrawal of this exact scope head.') : t('I independently confirm these exact scope obligations, examples and gaps, not inferred code behavior.')}</label>
          <button type="button" className="small-btn primary" disabled={!state.canSubmit} onClick={state.submit}>{t('Record scope decision')}</button>
        </fieldset>}
      </>}
    </>}
  </section>
}
