import { useHttpFixtureHistory } from '../../../../../domains/quality-loop/useHttpFixtureHistory'
import { matchesCaseSetupReference, type CaseSetupPlan } from '../../../../../domains/quality-loop/runPlanCaseValidation'
import type { CaseExecutionFields } from '../../../../../domains/quality-loop/types/runPlanCaseJobs'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function RunPlanCaseSetupPicker({ plan, actorId, setups, disabled, onChoose }: {
  plan: CaseSetupPlan; actorId: string; setups: CaseExecutionFields['setups']; disabled: boolean
  onChoose: (caseId: string, commandId: string) => void
}) {
  const { t } = useI18n(), history = useHttpFixtureHistory(plan.project_id, actorId)
  const rows = history.rows
  const candidates = rows && setups.map((setup) => ({ ...setup,
    options: rows.filter((row) => matchesCaseSetupReference(row, plan, setup.caseId)),
  })).filter((setup) => setup.options.length > 0)

  return <div className="case-setup-picker">
    <button type="button" className="small-btn" aria-expanded={history.open} disabled={disabled} onClick={history.toggle}>
      {t('Find setup commands for this plan')}
    </button>
    {history.open && <>
      <p>{t('Choosing a command only fills the reference. Check the references before independently confirming execution.')}</p>
      {history.list.isFetching && <p role="status">{t('Verifying original commands and source access...')}</p>}
      {history.failed && <p role="alert">{t('Original command history changed or could not be verified. Protected metadata is hidden; reload to check current access and state.')}</p>}
      {candidates?.length === 0 && <p>{t('No matching setup commands on the pages loaded. You can enter a command ID directly.')}</p>}
      {candidates?.map(({ caseId, commandId, options }) => <label key={caseId}>
        {t('Choose a saved setup for {case}', { case: caseId })}
        <select disabled={disabled} value={options.some((item) => item.invocation_id === commandId) ? commandId : ''}
          onChange={(event) => {
            const choice = options.find((item) => item.invocation_id === event.target.value)
            if (choice) onChoose(caseId, choice.invocation_id)
          }}>
          <option value="" disabled>{t('Select a setup command')}</option>
          {options.map((item) => <option key={item.invocation_id} value={item.invocation_id}>{item.attempt_id} · {item.invocation_id}</option>)}
        </select>
      </label>)}
      {history.list.hasNextPage && !history.failed && <button type="button" className="small-btn"
        disabled={disabled || history.list.isFetching} onClick={history.loadMore}>{t('Load more test data operations')}</button>}
      {history.failed && <button type="button" className="small-btn" disabled={disabled || history.list.isFetching}
        onClick={history.reload}>{t('Reload test data history')}</button>}
    </>}
  </div>
}
