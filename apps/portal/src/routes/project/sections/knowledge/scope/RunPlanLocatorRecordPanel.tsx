import { useState } from 'react'
import { useRunPlanLocatorRecord } from '../../../../../domains/quality-loop/useRunPlanLocatorRecord'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function RunPlanLocatorRecordPanel({ plan, actorId, current, onFailure }: {
  plan: RunPlanArchive; actorId: string; current: boolean; onFailure: () => void
}) {
  const { t } = useI18n(), state = useRunPlanLocatorRecord(plan, actorId, current, onFailure)
  const [archiveOpen, setArchiveOpen] = useState('')
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Independent source locator records')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Archive request source locators')}</button>
    {state.open && <>
      <p>{t('Independently archive every original request and frozen source locator. Static evidence does not authorize execution or prove business coverage.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload original locator command')}</button>
      {state.busy && <p role="status">{t('Verifying independently archived locators...')}</p>}
      {!state.canRegister && <p>{t('New locator registration requires current original inputs. Historical records remain readable.')}</p>}
      {state.failed && <p role="alert">{t('Original locator evidence could not be verified. Protected content is hidden.')}</p>}
      {(state.stored.invalid || state.recovery.isError || state.write.isError && !state.original) && <p role="alert">{t('Locator acknowledgement is unknown. Reload only reads the original command; it never repeats parsing or registration.')}</p>}
      {!state.result && (!state.stored.attempt || state.original?.command.status === 'waiting_confirmation') && <div className="scope-record">
        <details><summary>{t('Inspect exact locator registration request')}</summary><pre>{JSON.stringify(state.input, null, 2)}</pre></details>
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.canRegister || state.stored.invalid || state.failed}
          onChange={(event) => state.confirm(event.target.checked)} /><span>{t('I independently confirm archival of this exact plan and all original source revisions. No runtime routing, fixtures, execution or business coverage is approved.')}</span></label>
        {!state.stored.attempt && <button type="button" className="small-btn primary" disabled={!state.maySave} onClick={state.save}>{t('Record original source locators')}</button>}
        {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn primary" disabled={!state.mayConfirm} onClick={state.confirmOriginal}>{t('Confirm original locator registration')}</button>}
      </div>}
      {state.original && <div className="scope-record"><strong>{t('Original locator registration command')}</strong><code>{state.original.command.id}</code><code>{state.original.command.status}</code></div>}
      {state.result && <div className="scope-record" data-testid="original-locator-record">
        <strong>{t('Source locators archived; execution remains unauthorized')}</strong>
        <code>{state.result.metadata.record_id}</code><code>{state.result.metadata.report_hash}</code>
        <p>{t('{count} original actions inspected; executed and passed counts remain zero.', { count: state.result.metadata.summary.locator_count })}</p>
        <p>{t('Historical source bytes were rechecked without parsing. This is not live routing or a test pass.')}</p>
        <details key={state.result.metadata.record_id} onToggle={(event) => setArchiveOpen(event.currentTarget.open ? state.result!.metadata.record_id : '')}>
          <summary>{t('Inspect complete original locator archive')}</summary>
          {archiveOpen === state.result.metadata.record_id && <pre>{JSON.stringify(state.result.archive, null, 2)}</pre>}
        </details>
        <button type="button" className="small-btn" disabled={state.busy} onClick={state.another}>{t('Prepare another independent locator record')}</button>
      </div>}
    </>}
  </section>
}
