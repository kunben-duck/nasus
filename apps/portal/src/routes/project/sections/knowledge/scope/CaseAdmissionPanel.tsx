import { useCaseApprovals } from '../../../../../domains/quality-loop/useCaseApprovals'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import type { RecordedMappingArchive } from '../../../../../domains/quality-loop/types/testDesignMapping'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeText } from './ScopeInputs'

export function CaseAdmissionPanel({ draft, mapping, sessionId }: { draft: GenerationArchive; mapping: RecordedMappingArchive; sessionId: string }) {
  const { t, tx } = useI18n(), state = useCaseApprovals(draft, mapping, sessionId), view = state.view
  return <section className="scope-record" aria-label={t('Independent case admission')}>
    <button className="small-btn" type="button" disabled={state.busy} aria-expanded={state.open} onClick={state.toggle}>{t('Inspect case admission')}</button>
    {state.open && <>
      <p>{t('Mapping review does not approve cases for automation. This separate decision fixes the original cases and expected results; it grants no model or execution permission.')}</p>
      <button className="small-btn" type="button" disabled={state.busy} onClick={state.reload}>{t('Reload case admission')}</button>
      {state.busy && <p role="status">{t('Verifying original cases, authority and admission history...')}</p>}
      {(state.failed || state.write.isError) && <p role="alert">{t('Case admission could not be verified. Reload to inspect the original state; no automatic write retry was sent.')}</p>}
      {state.write.isSuccess && <p role="status">{t('Case admission recorded; generation and execution remain separate gates.')}</p>}
      {view && <div data-testid="case-admission-preview">
        <p>{t('{cases} fixed cases and {obligations} original obligations.', { cases: view.basis.case_pins.length, obligations: view.basis.obligation_denominator })}</p>
        <code>{view.basis.input_digest}</code>
        {!view.input_current && <p>{t('Original inputs are no longer current. You may inspect or withdraw their admission, but cannot approve them again.')}</p>}
        {view.head ? <p>{tx(view.head.status)} · {view.head.authority_actor} · <time>{view.head.recorded_at}</time></p>
          : <p>{t('No independent case admission has been recorded.')}</p>}
        {view.prepared.cases.map((item) => <details key={item.case_id}><summary>{item.title}</summary><code>{item.case_id}</code>
          <ol>{item.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
          <ul>{item.assertions.map((a) => <li key={a.row_id}><code>{a.row_id}</code> {a.oracle.expected_result}</li>)}</ul></details>)}
        {view.can_review && <div className="scope-actions">
          <button className="small-btn" type="button" disabled={state.busy || !view.input_current} onClick={() => state.begin(false)}>{t('Approve these exact cases')}</button>
          <button className="small-btn" type="button" disabled={state.busy || !state.mayWithdraw} onClick={() => state.begin(true)}>{t('Withdraw case admission')}</button>
        </div>}
        {state.editing && view.can_review && <fieldset disabled={state.busy || !state.write.isIdle}>
          <legend>{t('New independent case decision')}</legend>
          <ScopeText label={t('Review reason')} value={state.reason} onChange={state.explain} />
          <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
            {state.decision === 'withdraw' ? t('I confirm withdrawal of this exact case admission head.')
              : t('I independently approve these exact cases and original expected results for future automation input. No generation, execution or test pass is authorized.')}</label>
          <button className="small-btn primary" type="button" disabled={!state.canSubmit} onClick={state.submit}>{t('Record case decision')}</button>
        </fieldset>}
      </div>}
    </>}
  </section>
}
