import { useHttpFixtureOperation } from '../../../../../domains/quality-loop/useHttpFixtureOperation'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import type { FixtureRecipeView } from '../../../../../domains/quality-loop/types/httpFixtureRecipes'
import type { FixtureCommandStage, FixtureOperation } from '../../../../../domains/quality-loop/types/httpFixtureOperations'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../../../shared/i18n/messages'

export function HttpFixtureOperationPanel({ plan, recipe, actorId, current, onFailure }: {
  plan: RunPlanArchive; recipe: FixtureRecipeView; actorId: string; current: boolean; onFailure: () => void
}) {
  const { t } = useI18n(), s = useHttpFixtureOperation(plan, recipe, actorId, current, onFailure)
  const stages: { stage: FixtureCommandStage; label: MessageKey; consent: MessageKey; visible: boolean; command?: { id: string; status: string } }[] = [
    { stage: 'grant', label: 'Record independent fixture permission', visible: !!s.prepared && (!s.stored.attempt || s.grant?.command.status === 'waiting_confirmation'), command: s.grant?.command,
      consent: 'I independently authorize only this preparation or cleanup scope on the original environment for 15 minutes. No request will execute at this step.' },
    { stage: 'execute', label: 'Execute confirmed fixture operation', visible: !!s.grant?.grant && (!s.stored.attempt?.execute || s.execution?.command.status === 'waiting_confirmation'), command: s.execution?.command,
      consent: 'I independently confirm executing this exact fixture operation and grant. Results do not approve business coverage or restore the baseline.' },
    { stage: 'cancel', label: 'Cancel original fixture operation', visible: s.execution?.command.status === 'running' && (!s.stored.attempt?.cancel || s.cancellation?.status === 'waiting_confirmation'), command: s.cancellation,
      consent: 'I independently confirm cancelling the original operation. Cancellation does not undo requests, guarantee the target stopped or clean up created resources.' },
  ]
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Independent fixture operations')}>
    <button type="button" className="small-btn" aria-expanded={s.open} disabled={s.busy} onClick={s.toggle}>{t('Prepare or clean up test data')}</button>
    {s.open && <>
      <p>{t('Verify the original environment, authorize one bounded operation, then independently confirm execution. Cleanup must keep the same attempt ID as preparation.')}</p>
      <button type="button" className="small-btn" disabled={s.busy} onClick={s.reload}>{t('Reload original fixture operation')}</button>
      {s.busy && <p role="status">{t('Verifying original fixture operation...')}</p>}
      {(s.unavailable || s.write.isError) && <p role="alert">{t('Fixture operation acknowledgement is unavailable. Reload only reads original commands; it never resends or confirms them automatically.')}</p>}
      {s.failed && <p role="alert">{t('Original fixture operation could not be verified. Protected content is hidden.')}</p>}
      {!s.canOperate && <p>{t('Preparation requires current inputs. Historical cleanup still requires its own permission and confirmation.')}</p>}
      {!s.stored.attempt && !s.stored.invalid && <div className="fixture-operation-fields">
        <label>{t('Original environment command ID')}<input value={s.fields.environmentCommandId} maxLength={128} autoComplete="off" disabled={s.busy}
          onChange={(e) => s.edit({ environmentCommandId: e.target.value })} /></label>
        <label>{t('Fixture attempt ID')}<input value={s.fields.attemptId} maxLength={128} autoComplete="off" disabled={s.busy}
          onChange={(e) => s.edit({ attemptId: e.target.value })} /></label>
        <label>{t('Fixture operation')}<select value={s.fields.operation} disabled={s.busy} onChange={(e) => s.edit({ operation: e.target.value as FixtureOperation })}>
          <option value="setup">{t('Prepare test data')}</option><option value="cleanup">{t('Clean up original resources')}</option></select></label>
        <label>{t('Operation timeout (ms)')}<input type="number" min={1000} max={120000} step={1000} value={s.fields.timeoutMs} disabled={s.busy}
          onChange={(e) => s.edit({ timeoutMs: Number(e.target.value) })} /></label>
        <button type="button" className="small-btn" disabled={s.busy || !s.fields.environmentCommandId} onClick={s.verifyEnvironment}>{t('Verify original environment for this operation')}</button>
      </div>}
      {s.prepared && !s.failed && <div className="scope-record">
        <strong>{t('Original fixture scope')}</strong><code>{s.fields.attemptId}</code><code>{s.fields.operation}</code>
        <code>{s.prepared.value.metadata.record_id}</code><code>{s.prepared.value.metadata.inventory_hash}</code>
        <details><summary>{t('Inspect exact fixture permission request')}</summary><pre>{JSON.stringify(s.prepared.input, null, 2)}</pre></details>
      </div>}
      {!s.failed && stages.filter((item) => item.visible).map((item) => <div className="scope-record" key={item.stage}>
        <label className="context-pack-consent"><input type="checkbox" checked={s.confirmed(item.stage)} disabled={s.busy || s.unavailable}
          onChange={(e) => s.confirm(item.stage, e.target.checked)} /><span>{t(item.consent)}</span></label>
        <button type="button" className="small-btn primary" disabled={!s.mayWrite(item.stage)} onClick={() => s.submit(item.stage)}>
          {t(item.command?.status === 'waiting_confirmation' ? 'Confirm original fixture command' : item.label)}</button>
      </div>)}
      {!s.failed && s.grant && <div className="scope-record" data-testid="original-fixture-grant"><strong>{t('Original fixture permission')}</strong>
        <code>{s.grant.command.id}</code><code>{s.grant.command.status}</code>
        {s.grant.grant && <><code>{s.grant.grant.metadata.record_id}</code><p>{t('Expires at {time}. The backend checks its lifetime and current access before dispatch.', { time: s.grant.grant.metadata.expires_at })}</p></>}
      </div>}
      {!s.failed && s.execution && <div className="scope-record" data-testid="original-fixture-operation"><strong>{t('Original fixture execution command')}</strong>
        <code>{s.execution.command.id}</code><code>{s.execution.command.status}</code>
        {s.execution.job?.schema === 'nasus.http-fixture-job.v2' && <p>{t('The original command is still in preparation or stopped before binding. No target observation is recorded.')}</p>}
        {s.execution.job?.phases.map((phase) => <div key={phase.phase}><code>{phase.phase}</code><code>{phase.state}</code>
          {phase.state === 'observed' && <code>{phase.result_status}</code>}
          {phase.state === 'outcome_unknown' && <p>{t('This request has an unknown outcome. Automatic resending and new operation shortcuts are blocked.')}</p>}
        </div>)}
        {s.execution.job?.cancellation_requested && <p>{t(s.execution.job.cancellation_delivered ? 'Cancellation was delivered, but target stop, cleanup and baseline restoration remain unverified.' : 'Cancellation is recorded and awaiting delivery. Do not start a replacement operation.')}</p>}
        <p>{t('Fixture observations only: completed does not mean business tests passed. Coverage and baseline restoration remain unverified.')}</p>
        {s.execution.job?.status === 'completed' && <button type="button" className="small-btn" disabled={s.busy || s.unavailable} onClick={s.next}>{t('Prepare the next independently confirmed operation')}</button>}
      </div>}
      {!s.failed && s.cancellation && <div className="scope-record"><strong>{t('Original fixture cancellation command')}</strong><code>{s.cancellation.id}</code><code>{s.cancellation.status}</code></div>}
    </>}
  </section>
}
