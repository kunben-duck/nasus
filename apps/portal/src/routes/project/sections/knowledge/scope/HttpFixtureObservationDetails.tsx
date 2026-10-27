import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { FixtureOriginalObservation } from '../../../../../domains/quality-loop/types/httpFixtureObservations'

export function HttpFixtureObservationDetails({ value }: { value: FixtureOriginalObservation }) {
  const { t } = useI18n()
  return <div className="scope-record" data-testid="fixture-original-observation">
    <strong>{t('Original persisted operation phases')}</strong><code>{value.state}</code>
    {value.state === 'outcome_unknown' && <p role="alert">{t('The effect of the original operation is unknown. Do not resend it; cancellation does not prove rollback.')}</p>}
    {value.state === 'not_execution' && <p>{t('This is a permission command, not a target execution.')}</p>}
    {value.state === 'not_confirmed' && <p>{t('No execution has been confirmed for this command.')}</p>}
    {value.job?.schema === 'nasus.http-fixture-job.v2' && <p>{t('Only original preparation is recorded. No target observation is available.')}</p>}
    {value.execution && <p>{t('Original fixture execution command')}: <code>{value.execution.invocation_id}</code></p>}
    {value.job?.phases.map((phase) => <div className="scope-record" key={phase.claim_id}>
      <code>{phase.phase}</code><code>{phase.state}</code><code>{phase.claim_id}</code>
      {phase.state === 'observed' && <><code>{phase.result_status}</code><code>{phase.result_digest}</code></>}
    </div>)}
    <p>{t('These are original persisted observations, not live target checks, business coverage or baseline restoration.')}</p>
  </div>
}
