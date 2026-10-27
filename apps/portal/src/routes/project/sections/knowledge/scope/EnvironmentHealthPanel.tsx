import { useEnvironmentHealth } from '../../../../../domains/quality-loop/useEnvironmentHealth'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import type { RunPlanBuildArchive } from '../../../../../domains/quality-loop/types/runPlanBuilds'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function EnvironmentHealthPanel({ plan, binding, actorId, current, onFailure }: {
  plan: RunPlanArchive; binding: RunPlanBuildArchive; actorId: string; current: boolean; onFailure: () => void
}) {
  const { t } = useI18n(), state = useEnvironmentHealth(plan, binding, actorId, current, onFailure)
  const labels = { pg: t('PostgreSQL health'), redis: t('Redis health'), target: t('Application health') }
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Original instance health')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect original health')}</button>
    {state.open && <>
      <p>{t('Independently record PostgreSQL, Redis and application health on the exact original instances. This is a historical observation, not test execution or a live readiness guarantee.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload original health command')}</button>
      {state.busy && <p role="status">{t('Verifying original health record...')}</p>}
      {!state.canRegister && <p>{t('New health checks require current original inputs and the supported local target. Historical health remains readable.')}</p>}
      {state.failed && <p role="alert">{t('Original health provenance could not be verified. Protected content is hidden.')}</p>}
      {(state.stored.invalid || state.recovery.isError || state.write.isError && !state.original) && <p role="alert">{t('Health acknowledgement is unknown. Reload only reads the original command and never repeats probes or registration.')}</p>}
      {!state.result && (!state.stored.attempt || state.original?.command.status === 'waiting_confirmation') && <div className="scope-record">
        <details><summary>{t('Inspect exact health request')}</summary><pre>{JSON.stringify(state.input, null, 2)}</pre></details>
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.canRegister || state.stored.invalid || state.failed}
          onChange={(event) => state.confirm(event.target.checked)} /><span>{t('I independently confirm these original health probes and their archival. This does not authorize tests or verify fixtures, physical isolation or business coverage.')}</span></label>
        {!state.stored.attempt && <button type="button" className="small-btn primary" disabled={!state.maySave} onClick={state.save}>{t('Record original health')}</button>}
        {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn primary" disabled={!state.mayConfirm} onClick={state.confirmOriginal}>{t('Confirm original health registration')}</button>}
      </div>}
      {state.original && <div className="scope-record"><strong>{t('Original health command')}</strong><code>{state.original.command.id}</code><code>{state.original.command.status}</code></div>}
      {state.result && <div className="scope-record" data-testid="original-health-record">
        <strong>{t('Health recorded; target execution remains unauthorized')}</strong>
        <code>{state.result.metadata.record_id}</code><code>{state.result.metadata.health_hash}</code>
        <p>{t('Observed at')} <time dateTime={state.result.metadata.observed_at}>{state.result.metadata.observed_at}</time></p>
        <ul>{state.result.metadata.health_checks.map((check) => <li key={check.role}><strong>{labels[check.role]}</strong>: {t(check.healthy ? 'Healthy at observation' : 'Unhealthy at observation')}</li>)}</ul>
        <p>{t('Health does not verify fixtures, locators, physical isolation or business coverage. Executed and passed counts remain zero.')}</p>
        <details><summary>{t('Inspect private original health responses')}</summary><pre>{JSON.stringify(state.result.archive.observation, null, 2)}</pre></details>
        <button type="button" className="small-btn" disabled={state.busy} onClick={state.another}>{t('Prepare another original health check')}</button>
      </div>}
    </>}
  </section>
}
