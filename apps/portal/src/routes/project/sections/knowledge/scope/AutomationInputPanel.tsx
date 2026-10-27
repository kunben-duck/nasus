import { useAutomationInput } from '../../../../../domains/quality-loop/useAutomationInput'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import type { RecordedMappingArchive } from '../../../../../domains/quality-loop/types/testDesignMapping'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

const reasons = {
  automation_environment_not_bound: 'Bind the test environment and target build.',
  api_or_dom_locator_evidence_not_bound: 'Provide verified API or page locator evidence.',
  fixture_setup_cleanup_not_bound: 'Confirm test data, setup and cleanup.',
  model_budget_not_bound: 'Select the generation model and approve its budget.',
  script_generation_and_independent_review_required: 'Generate and independently review scripts before execution.',
} as const

export function AutomationInputPanel({ draft, mapping, sessionId }: { draft: GenerationArchive; mapping: RecordedMappingArchive; sessionId: string }) {
  const { t } = useI18n(), state = useAutomationInput(draft, mapping, sessionId), value = state.value
  return <section className="scope-record" aria-label={t('Automation input check')}>
    <button className="small-btn" type="button" aria-expanded={state.open} disabled={!state.available || state.busy} onClick={state.toggle}>{t('Inspect automation inputs')}</button>
    {!state.available && <p>{t('A current complete mapping with at most 512 accepted cases is required. No cases are silently omitted.')}</p>}
    {state.open && <>
      <p>{t('This read-only check preserves reviewed cases and expected results. It does not generate scripts or authorize execution.')}</p>
      <button className="small-btn" type="button" disabled={state.busy || !state.available} onClick={state.reload}>{t('Recheck automation inputs')}</button>
      {state.busy && <p role="status">{t('Verifying fixed cases, source access and current review...')}</p>}
      {state.failed && <p role="alert">{t('Automation inputs could not be verified. Recheck current access and review; no automatic retry was sent.')}</p>}
      {value && <div data-testid="automation-input-preview">
        <p>{t('{cases} reviewed cases preserve {obligations} obligations and {constraints} source constraints.', {
          cases: value.cases.length, obligations: value.obligation_denominator, constraints: value.constraint_denominator })}</p>
        <code>{value.input_digest}</code><p>{t('Script generation and execution remain blocked:')}</p>
        <ul>{value.readiness.reason_codes.map((reason) => <li key={reason}>{t(reasons[reason])}</li>)}</ul>
        {value.cases.map((item) => <details key={item.case_id}><summary>{item.title}</summary><code>{item.case_id}</code>
          <ol>{item.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
          <ul>{item.assertions.map((assertion) => <li key={assertion.row_id}><code>{assertion.row_id}</code> {assertion.oracle.expected_result}</li>)}</ul>
        </details>)}
      </div>}
    </>}
  </section>
}
