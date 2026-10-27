import { useEnvironmentRecord } from '../../../../../domains/quality-loop/useEnvironmentRecord'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import type { RunPlanBuildArchive } from '../../../../../domains/quality-loop/types/runPlanBuilds'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function EnvironmentRecordPanel({ plan, binding, actorId, current, onFailure }: {
  plan: RunPlanArchive; binding: RunPlanBuildArchive; actorId: string; current: boolean; onFailure: () => void
}) {
  const { t } = useI18n(), state = useEnvironmentRecord(plan, binding, actorId, current, onFailure)
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Original environment observation')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect environment observation')}</button>
    {state.open && <>
      <p>{t('Record an independently confirmed inspection of the original target and mounted build. This never deploys, runs tests or grants execution permission.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload original environment command')}</button>
      {state.busy && <p role="status">{t('Verifying original environment observation...')}</p>}
      {!state.canRegister && <p>{t('New observation requires current original inputs and the supported local target. Historical records remain readable.')}</p>}
      {state.failed && <p role="alert">{t('Environment provenance could not be verified. Protected content is hidden.')}</p>}
      {(state.stored.invalid || state.recovery.isError || state.write.isError && !state.original) && <p role="alert">{t('Environment acknowledgement is unknown. Reload only reads the original command and never repeats inspection or registration.')}</p>}
      {!state.result && (!state.stored.attempt || state.original?.command.status === 'waiting_confirmation') && <div className="scope-record">
        <details><summary>{t('Inspect exact environment request')}</summary><pre>{JSON.stringify(state.input, null, 2)}</pre></details>
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.canRegister || state.stored.invalid || state.failed}
          onChange={(event) => state.confirm(event.target.checked)} /><span>{t('I independently confirm recording this original environment observation. Fixtures, target execution and business coverage remain unverified and unauthorized.')}</span></label>
        {!state.stored.attempt && <button type="button" className="small-btn primary" disabled={!state.maySave} onClick={state.save}>{t('Record original environment')}</button>}
        {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn primary" disabled={!state.mayConfirm} onClick={state.confirmOriginal}>{t('Confirm original environment registration')}</button>}
      </div>}
      {state.original && <div className="scope-record"><strong>{t('Original environment command')}</strong><code>{state.original.command.id}</code><code>{state.original.command.status}</code></div>}
      {state.result && <div className="scope-record" data-testid="original-environment-record">
        <strong>{t('Environment observation recorded; not live execution approval')}</strong>
        <code>{state.result.metadata.record_id}</code><code>{state.result.metadata.inventory_hash}</code>
        <p>{t('Observed at')} <time dateTime={state.result.metadata.observed_at}>{state.result.metadata.observed_at}</time></p>
        <p>{t('The original build and isolation configuration were inspected. Dependency health, fixtures, locators and business coverage are not verified. Executed and passed counts remain zero.')}</p>
        <details><summary>{t('Inspect private original inventory')}</summary><pre>{JSON.stringify(state.result.archive.observation.inventory, null, 2)}</pre></details>
        <button type="button" className="small-btn" disabled={state.busy} onClick={state.another}>{t('Prepare another environment observation')}</button>
      </div>}
    </>}
  </section>
}
