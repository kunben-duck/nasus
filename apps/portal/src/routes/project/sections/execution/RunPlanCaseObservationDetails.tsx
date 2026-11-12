import { summarizeCaseObservations } from '../../../../domains/quality-loop/runPlanCaseObservationSummary'
import type { CaseExecutionHistory } from '../../../../domains/quality-loop/types/runPlanCaseJobs'
import type { RunPlanValue } from '../../../../domains/quality-loop/types/runPlans'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function RunPlanCaseObservationDetails({ plan, history }: {
  plan: RunPlanValue; history: NonNullable<CaseExecutionHistory['history']>
}) {
  const { t, tx } = useI18n(), { counts, cases } = summarizeCaseObservations(plan, history)
  const { state } = history
  return <>
    <p>{t('{observed} of {total} planned cases have saved results.', { observed: state.observed_case_count, total: state.case_count })}</p>
    <ul className="case-observation-counts" aria-label={t('Case result summary')}>
      <li>{t('Passed: {count}', { count: counts.passed })}</li>
      <li>{t('Failed: {count}', { count: counts.failed })}</li>
      <li>{t('Errors or timeouts: {count}', { count: counts.error + counts.timed_out })}</li>
      <li>{t('Unknown effects: {count}', { count: counts.outcome_unknown })}</li>
      <li>{t('Not sent: {count}', { count: counts.not_dispatched })}</li>
    </ul>
    <ul className="case-observation-list">
      {cases.map((item) => <li key={item.id}>
        <details>
          <summary><span>{item.title}</span> <strong>{tx(item.status.replaceAll('_', ' '))}</strong></summary>
          <code>{item.id}</code>
          {item.oracles.length > 0 ? <ul>{item.oracles.map((oracle) => <li key={oracle.id}>
            <strong>{t('Step {step}: {status}', { step: oracle.step, status: tx(oracle.status) })}</strong>
            <p>{t('Expected: {result}', { result: oracle.expected })}</p>
            {oracle.responseStatus !== undefined && <p>{t('Observed HTTP status: {status}', { status: oracle.responseStatus })}</p>}
          </li>)}</ul> : <p>{t('No assertion result was recorded for this case.')}</p>}
        </details>
      </li>)}
    </ul>
    {state.outcome_unknown_case_count > 0 && <p role="alert">{t('Some original requests have unknown effects. Automatic resending and replacement attempts are blocked.')}</p>}
    {state.cancelled && <p>{t('Cancellation is recorded. Target stop, cleanup and baseline restoration remain unverified.')}</p>}
  </>
}
