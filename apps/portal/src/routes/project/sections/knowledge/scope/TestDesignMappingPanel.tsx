import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import { useTestDesignMapping } from '../../../../../domains/quality-loop/useTestDesignMapping'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AssertionMappingEditor } from './AssertionMappingEditor'
import { PartitionedMappingSummary } from './PartitionedMappingSummary'
import { MappingStagingPanel } from './MappingStagingPanel'
import { ScopeText } from './ScopeInputs'
import { AutomationInputPanel } from './AutomationInputPanel'
import { CaseAdmissionPanel } from './CaseAdmissionPanel'
import { AutomationScriptPanel } from './AutomationScriptPanel'

export function TestDesignMappingPanel({ draft, sessionId, onFailure }: { draft: GenerationArchive; sessionId: string; onFailure: () => void }) {
  const { t, tx } = useI18n(), state = useTestDesignMapping(draft, sessionId, onFailure)
  const view = state.view, content = state.content, assessment = content?.assessment
  return <section className="test-design-mapping" aria-label={t('Independent assertion mapping')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect assertion mapping')}</button>
    {state.open && <>
      <p>{t('Review the exact step and independent expected result for every proposed assertion. Accepted mappings do not prove automation, target execution or pass.')}</p>
      <button type="button" className="small-btn" disabled={state.write.isPending} onClick={state.reload}>{t('Reload mapping history')}</button>
      {state.busy && <p role="status">{t('Verifying mapping history and current source access...')}</p>}
      {state.write.isSuccess && <p role="status">{t('Mapping decision recorded; execution remains separately gated.')}<code>{state.write.data}</code></p>}
      {state.write.isError && <p role="alert">{state.stale ? t('Mapping inputs or head changed. Reload and independently confirm a new decision.')
        : t('Mapping decision was not acknowledged. Reload history before retrying; no automatic retry was sent.')}</p>}
      {view && <>
        {!view.scope_current && <p>{t('The original scope is stale or withdrawn. Historical mappings remain inspectable; new reviews are blocked.')}</p>}
        {!view.head && <p>{t('No independent mapping review has been recorded.')}</p>}
        {content && <div className="scope-record" aria-label={t('Recorded mapping decision')}>
          <strong>{content.revision.status === 'withdrawn' ? t('Withdrawn mapping') : content.current_use.mapping_current ? t('Current reviewed mapping') : t('Historical mapping; not current')}</strong>
          <code>{content.revision.revision_id}</code><small>{content.revision.authority_actor} · <time>{content.revision.recorded_at}</time></small><p>{content.request.reason}</p>
          {assessment && <><p>{t('{mapped}/{total} obligations have accepted assertions; {accepted} accepted, {rejected} rejected, {deferred} deferred assertion pairs.', {
            mapped: assessment.coverage.assertion_mapped_count, total: assessment.coverage.obligation_denominator,
            accepted: assessment.accepted_assertion_count, rejected: assessment.rejected_assertion_count, deferred: assessment.deferred_assertion_count })}</p>
            <p>{content.current_use.mapping_complete ? t('Current mapping has no explicit gaps. Automation and execution still need separate approval.')
              : t('This mapping is incomplete, historical or withdrawn. It cannot authorize automation or execution.')}</p>
            {'part_set' in content ? <PartitionedMappingSummary key={content.revision.revision_id} content={content} />
              : <AssertionMappingEditor draft={draft} values={content.request.mappings!} readOnly onChange={() => {}} />}</>}
        </div>}
        <label>{t('Mapping history')}<select value={state.selected} disabled={state.busy} onChange={(event) => state.choose(event.target.value)}>
          <option value="">{t('Current mapping head')}</option>{view.history.map((item) => <option key={item.revision_id} value={item.revision_id}>{item.sequence} · {tx(item.status)} · {item.recorded_at}</option>)}</select></label>
        {content?.current_use.mapping_current && !state.selected && !state.editing && <AutomationInputPanel
          key={`${sessionId}:${content.revision.revision_id}:${content.revision.artifact_hash}`} draft={draft} mapping={content} sessionId={sessionId} />}
        {content?.revision.status === 'reviewed' && assessment?.mapping_complete && !state.editing && <CaseAdmissionPanel
          key={`admission:${sessionId}:${content.revision.revision_id}:${content.revision.artifact_hash}`}
          draft={draft} mapping={content} sessionId={sessionId} />}
        {content?.revision.status === 'reviewed' && assessment?.mapping_complete && !state.editing && <AutomationScriptPanel
          key={`scripts:${sessionId}:${content.revision.revision_id}:${content.revision.artifact_hash}`}
          draft={draft} mapping={content} sessionId={sessionId} onFailure={onFailure} />}
        {view.can_review ? <div className="scope-actions">
          <button type="button" className="small-btn" disabled={state.busy || !state.mayReview} onClick={() => state.begin()}>{t('Review assertion mappings')}</button>
          <button type="button" className="small-btn" disabled={state.busy || view.head?.revision.status !== 'reviewed'} onClick={() => state.begin(true)}>{t('Withdraw mapping')}</button>
        </div> : <p>{t('Only a project reviewer can record an independent mapping decision.')}</p>}
        {state.editing && !state.selected && view.can_review && <fieldset disabled={state.busy || !state.write.isIdle}>
          <legend>{t('New mapping decision')}</legend>
          {state.decision === 'review' && <AssertionMappingEditor draft={draft} values={state.values} onChange={state.edit} />}
          <ScopeText label={t('Review reason')} value={state.reason} onChange={state.explain} />
          <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
            {state.decision === 'withdraw' ? t('I confirm withdrawal of this exact mapping head.')
              : t('I independently confirm every exact step, oracle and mapping decision. This is not evidence of test execution.')}</label>
          <button type="button" className="small-btn primary" disabled={!state.canSubmit} onClick={state.submit}>{t('Record mapping decision')}</button>
        </fieldset>}
        {view.can_review && !state.editing && !state.selected && <MappingStagingPanel draft={draft} sessionId={sessionId}
          previous={view.head?.revision.revision_id ?? null} scopeCurrent={view.scope_current} onFailure={onFailure} onDone={state.reload} />}
      </>}
    </>}
  </section>
}
