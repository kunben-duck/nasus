import { useRunPlanCaseHistoryLookup } from '../../../../domains/quality-loop/useRunPlanCaseHistoryLookup'
import type { RunPlanArchive } from '../../../../domains/quality-loop/types/runPlans'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { RunPlanCaseObservationDetails } from './RunPlanCaseObservationDetails'
import '../knowledge/scope/run-plan.css'

export function RunPlanCaseHistoryLookup({ scope, actorId }: { scope: RunPlanArchive | string; actorId: string }) {
  const { t, tx } = useI18n(), lookup = useRunPlanCaseHistoryLookup(scope, actorId)
  const history = lookup.original?.history?.history
  return <details className="scope-record run-plan-panel run-plan-case-panel case-history-lookup">
    <summary>{t('Find a past execution by command ID')}</summary>
    <p>{t('Look up an original execution by its command ID, including one started in another browser. This only reads saved records.')}</p>
    <form onSubmit={(event) => { event.preventDefault(); lookup.read() }}>
      <label>{t('Original execution command ID')}
        <input type="text" value={lookup.draft} onChange={(event) => lookup.edit(event.target.value)} maxLength={128} spellCheck={false} />
      </label>
      <button className="small-btn" type="submit" disabled={!lookup.canRead}>{t('Find execution results')}</button>
    </form>
    {lookup.busy && <p role="status">{t('Verifying original case execution...')}</p>}
    {lookup.failed && <p role="alert">{t('No verified execution is available for this command and plan. Check the ID and your access.')}</p>}
    {lookup.original && <>
      <code>{lookup.original.command.id}</code><code>{tx(lookup.original.command.status)}</code>
      {history ? <RunPlanCaseObservationDetails plan={lookup.original.plan.artifact.plan} history={history} />
        : <p>{t('The original task has not bound an execution roster. No target observation is recorded.')}</p>}
      <p>{t('These are original execution observations, not formal coverage or release evidence. Completed does not mean every test passed.')}</p>
    </>}
  </details>
}
