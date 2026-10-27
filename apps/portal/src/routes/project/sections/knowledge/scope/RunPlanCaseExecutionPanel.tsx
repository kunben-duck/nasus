import { useRunPlanCaseJob } from '../../../../../domains/quality-loop/useRunPlanCaseJob'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import type { CaseCommandStage } from '../../../../../domains/quality-loop/types/runPlanCaseJobs'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function RunPlanCaseExecutionPanel({ plan, actorId, current, onFailure }: {
  plan: RunPlanArchive; actorId: string; current: boolean; onFailure: () => void
}) {
  const { t, tx } = useI18n(), s = useRunPlanCaseJob(plan, actorId, current, onFailure)
  const history = s.original?.history, state = history?.history?.state
  const stages: CaseCommandStage[] = []
  if (s.prepared && !s.stored.attempt || s.original?.command.status === 'waiting_confirmation') stages.push('execute')
  if (s.original?.command.status === 'running' && (!s.stored.attempt?.cancel || s.control?.status === 'waiting_confirmation')) stages.push('cancel')
  return <section className="run-plan-panel run-plan-case-panel test-design-mapping" aria-label={t('Original business case execution')}>
    <button type="button" className="small-btn" aria-expanded={s.open} disabled={s.busy} onClick={s.toggle}>{t('Execute original business cases')}</button>
    {s.open && <>
      <p>{t('Keep every original case and setup reference. Execution requires its own confirmation; fixture preparation does not authorize business requests.')}</p>
      <button type="button" className="small-btn" disabled={s.busy} onClick={s.reload}>{t('Reload original case command and access')}</button>
      {s.busy && <p role="status">{t('Verifying original case execution...')}</p>}
      {(s.unavailable || s.write.isError) && <p role="alert">{t('The original acknowledgement is unavailable. Reload only reads the same command; it never resends or confirms automatically.')}</p>}
      {s.failed && <p role="alert">{t('Original case execution could not be verified. Protected results are hidden.')}</p>}
      {!s.canExecute && <p>{t('The selected plan is historical or no longer current. Inspect saved execution only; starting new work is blocked.')}</p>}
      {!s.stored.attempt && !s.stored.invalid && !s.failed && <div className="fixture-operation-fields case-execution-fields">
        <label>{t('Original environment command ID')}<input value={s.fields.environmentCommandId} disabled={s.busy} maxLength={256}
          onChange={(e) => s.edit({ environmentCommandId: e.target.value })} /></label>
        <label>{t('Original locator command ID')}<input value={s.fields.locatorCommandId} disabled={s.busy} maxLength={256}
          onChange={(e) => s.edit({ locatorCommandId: e.target.value })} /></label>
        <label>{t('Independent business attempt ID')}<input value={s.fields.runId} disabled={s.busy} maxLength={256}
          onChange={(e) => s.edit({ runId: e.target.value })} /></label>
        <label>{t('Per-case timeout (ms)')}<input type="number" min={1000} max={120000} value={s.fields.timeoutMs} disabled={s.busy}
          onChange={(e) => s.edit({ timeoutMs: Number(e.target.value) })} /></label>
        <fieldset><legend>{t('Setup commands for every original case')}</legend>
          {s.fields.setups.map((v, i) => <label key={v.caseId}><code>{v.caseId}</code><input aria-label={t('Setup command for {case}', { case: v.caseId })}
            value={v.commandId} maxLength={256} disabled={s.busy}
            onChange={(e) => s.edit({ setups: s.fields.setups.map((item, n) => n === i ? { ...item, commandId: e.target.value } : item) })} /></label>)}
        </fieldset>
        <button type="button" className="small-btn" disabled={!s.canVerify} onClick={s.verify}>{t('Check original execution references')}</button>
      </div>}
      {s.prepared && !s.failed && <div className="scope-record"><strong>{t('Original references checked; execution remains unauthorized')}</strong>
        <p>{t('The backend rechecks target health, setup observations, cleanup and source access after confirmation. These references are not a live permission.')}</p>
        <details><summary>{t('Inspect exact business execution request')}</summary><pre>{JSON.stringify(s.prepared, null, 2)}</pre></details>
      </div>}
      {!s.failed && stages.map((stage) => <div className="scope-record" key={stage}>
        <label className="context-pack-consent"><input type="checkbox" disabled={s.busy || stage === 'execute' && !s.canExecute}
          checked={s.confirmed(stage)} onChange={(e) => s.confirm(stage, e.target.checked)} />
          <span>{t(stage === 'execute' ? 'I independently confirm these exact cases and target references. Observations do not approve business coverage or release readiness.'
            : 'I independently confirm cancelling this original case task. Cancellation does not undo requests or prove cleanup.')}</span></label>
        <button type="button" className="small-btn primary" disabled={!s.mayWrite(stage)} onClick={() => s.submit(stage)}>
          {t(stage === 'execute' ? 'Confirm original business execution' : 'Confirm original business cancellation')}</button>
      </div>)}
      {s.original && <div className="scope-record" data-testid="original-case-execution"><strong>{t('Original business execution command')}</strong>
        <code>{s.original.command.id}</code><code>{tx(s.original.command.status)}</code>
        {history && !history.bound && <p>{t('The original task has not bound an execution roster. No target observation is recorded.')}</p>}
        {state && <><code>{tx(state.state)}</code><p>{t('{observed} of {total} original cases have observations; formal executed and passed counts remain zero.', {
          observed: state.observed_case_count, total: state.case_count })}</p>
          <ul>{state.cases.map((row) => <li key={row.case_id}><code>{row.case_id}</code><code>{tx(row.status)}</code></li>)}</ul>
          {state.outcome_unknown_case_count > 0 && <p role="alert">{t('Some original requests have unknown effects. Automatic resending and replacement attempts are blocked.')}</p>}
          {state.cancelled && <p>{t('Cancellation is recorded. Target stop, cleanup and baseline restoration remain unverified.')}</p>}
        </>}
        <p>{t('These are original execution observations, not formal coverage or release evidence. Completed does not mean every test passed.')}</p>
      </div>}
      {s.control && <div className="scope-record"><strong>{t('Original business cancellation command')}</strong><code>{s.control.id}</code><code>{tx(s.control.status)}</code></div>}
    </>}
  </section>
}
