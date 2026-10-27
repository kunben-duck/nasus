import { useState } from 'react'
import { useHttpFixtureRecipe } from '../../../../../domains/quality-loop/useHttpFixtureRecipe'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { HttpFixtureOperationPanel } from './HttpFixtureOperationPanel'

export function HttpFixtureRecipePanel({ plan, actorId, current, onFailure }: {
  plan: RunPlanArchive; actorId: string; current: boolean; onFailure: () => void
}) {
  const { t } = useI18n(), state = useHttpFixtureRecipe(plan, actorId, current, onFailure)
  const [archiveOpen, setArchiveOpen] = useState('')
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Independent fixture definitions')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Register fixture definition')}</button>
    {state.open && <>
      <p>{t('Save an explicit preparation and cleanup definition matching one original case. Registration never prepares data, executes requests or approves business coverage.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload original fixture registration')}</button>
      {state.busy && <p role="status">{t('Verifying original fixture definition...')}</p>}
      {!state.canRegister && <p>{t('New fixture registration requires current original inputs. Historical definitions remain readable.')}</p>}
      {state.failed && <p role="alert">{t('Original fixture definition could not be verified. Protected content is hidden.')}</p>}
      {(state.stored.invalid || state.recovery.isError || state.write.isError && !state.original) && <p role="alert">{t('Fixture acknowledgement is unknown. Reload only reads the original command; it never repeats registration or confirmation.')}</p>}
      {!state.stored.attempt && !state.stored.invalid && state.canRegister && <>
        <details className="scope-record"><summary>{t('Inspect original fixture declarations')}</summary><pre>{JSON.stringify(plan.artifact.plan.selection.fixtures, null, 2)}</pre></details>
        <label className="run-plan-fixture-input">{t('Complete HTTP fixture definition (JSON)')}
          <textarea value={state.text} disabled={state.busy} maxLength={128 * 1024} spellCheck={false} autoComplete="off"
            onChange={(event) => state.edit(event.target.value)} /></label>
        <p>{t('Use the complete nasus.http-fixture-manifest.v1 definition. Preserve the original manifest hash and all preconditions, setup, cleanup and expected results.')}</p>
        <button type="button" className="small-btn" disabled={state.busy || !state.text.trim()} onClick={state.prepare}>{t('Verify fixture against original plan')}</button>
      </>}
      {state.preview.isError && <p role="alert">{t('Fixture definition does not match the original plan or exceeds the supported limits. No registration was sent.')}</p>}
      {(state.prepared || state.original?.command.status === 'waiting_confirmation') && <div className="scope-record">
        <details><summary>{t('Inspect exact fixture registration request')}</summary><pre>{JSON.stringify(state.prepared ?? state.original?.input, null, 2)}</pre></details>
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.canRegister}
          onChange={(event) => state.confirm(event.target.checked)} /><span>{t('I independently confirm saving this exact fixture definition. This does not authorize preparation, cleanup, target execution or release.')}</span></label>
        {!state.stored.attempt && <button type="button" className="small-btn primary" disabled={!state.maySave} onClick={state.save}>{t('Save confirmed fixture definition')}</button>}
        {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn primary" disabled={!state.mayConfirm} onClick={state.confirmOriginal}>{t('Confirm original fixture registration')}</button>}
      </div>}
      {state.original && <div className="scope-record"><strong>{t('Original fixture registration command')}</strong><code>{state.original.command.id}</code><code>{state.original.command.status}</code></div>}
      {state.result && <div className="scope-record" data-testid="original-fixture-recipe">
        <strong>{t('Fixture definition saved; execution remains unauthorized')}</strong>
        <code>{state.result.metadata.record_id}</code><code>{state.result.metadata.case_id}</code><code>{state.result.metadata.data_manifest_hash}</code>
        <p>{t('Definition bytes verified only. Prepared, executed and passed counts remain zero; baseline restoration is not verified.')}</p>
        <details key={state.result.metadata.record_id} onToggle={(event) => setArchiveOpen(event.currentTarget.open ? state.result!.metadata.record_id : '')}>
          <summary>{t('Inspect complete original fixture archive')}</summary>
          {archiveOpen === state.result.metadata.record_id && <pre>{JSON.stringify(state.result.archive, null, 2)}</pre>}
        </details>
        <button type="button" className="small-btn" disabled={state.busy} onClick={state.another}>{t('Prepare another independent fixture definition')}</button>
        <HttpFixtureOperationPanel key={`${actorId}:${state.result.metadata.record_id}:${state.result.metadata.artifact_hash}`}
          plan={plan} recipe={state.result} actorId={actorId} current={current} onFailure={onFailure} />
      </div>}
    </>}
  </section>
}
