import { useAuthUser } from '../../../../../domains/platform/useAuthSession'
import { useRunPlan } from '../../../../../domains/quality-loop/useRunPlan'
import type { ScriptArchive, ScriptReviewArchive } from '../../../../../domains/quality-loop/types/automationScripts'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { RunPlanDeclarations } from './RunPlanDeclarations'
import { RunPlanBuildPanel } from './RunPlanBuildPanel'
import { RunPlanLocatorPanel } from './RunPlanLocatorPanel'
import { RunPlanLocatorRecordPanel } from './RunPlanLocatorRecordPanel'
import { HttpFixtureRecipePanel } from './HttpFixtureRecipePanel'
import { RunPlanCaseExecutionPanel } from './RunPlanCaseExecutionPanel'
import './run-plan.css'

interface Props { draft: ScriptArchive; review: ScriptReviewArchive; current: boolean; onFailure: () => void }
export function RunPlanPanel(props: Props) {
  const user = useAuthUser()
  if (!user.data || user.isError || user.isFetching) return null
  return <PlanPanel key={`${user.data.id}:${props.draft.metadata.script_revision_id}:${props.review.revision.revision_id}`} {...props} actorId={user.data.id} />
}
function PlanPanel({ draft, review, current, onFailure, actorId }: Props & { actorId: string }) {
  const { t } = useI18n(), state = useRunPlan(draft, review, actorId, current, onFailure)
  const original = state.original, result = state.result
  return <section className="test-design-mapping run-plan-panel" aria-label={t('Pinned execution plan')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.write.isPending} onClick={state.toggle}>{t('Prepare execution plan')}</button>
    {state.open && <>
      <p>{t('Save all original reviewed cases and code revisions with target declarations. Preparation does not authorize execution or prove any test passed.')}</p>
      <button type="button" className="small-btn" disabled={state.write.isPending} onClick={state.reload}>{t('Reload original plan and source access')}</button>
      {state.busy && <p role="status">{t('Verifying original plan inputs and source access...')}</p>}
      {(state.stored.invalid || state.recovery.isError || (state.write.isError && !original)) && <p role="alert">{t('Preparation acknowledgement could not be verified. Reload only reads the original command; no new preparation or confirmation is sent.')}</p>}
      {state.failed && <p role="alert">{t('Original plan provenance could not be verified. Protected content is hidden.')}</p>}
      {!state.canPrepare && <p>{t('This script review is historical, incomplete or withdrawn. Inspect saved plans only; new preparation is blocked.')}</p>}
      {state.source && <details className="scope-record"><summary>{t('All original code revisions')}</summary>
        <code>{state.source.image_revision_id}</code><code>{state.source.manifest_id}</code>
        <ul>{state.source.source_members.filter((item) => item.source_type === 'code' && item.status === 'captured').map((item) =>
          <li key={item.binding_id}><code>{item.binding_id}</code><code>{item.source_revision_id}</code></li>)}</ul>
      </details>}
      {!state.stored.attempt && !state.stored.invalid && state.source && state.canPrepare && <>
        <RunPlanDeclarations draft={draft} fields={state.fields} edit={state.edit} disabled={state.busy} />
        <button type="button" className="small-btn" disabled={!state.mayPreview} onClick={state.prepare}>{t('Preview exact execution plan')}</button>
      </>}
      {state.preview.isError && <p role="alert">{t('Plan preview was rejected. Check every target declaration and reload the original inputs before confirming.')}</p>}
      {(state.prepared || original?.command.status === 'waiting_confirmation') && <div className="scope-record">
        <strong>{t('Declarations only; target execution not authorized')}</strong>
        <code>{state.prepared?.request.plan_digest ?? original?.input.plan_digest}</code>
        <details><summary>{t('Inspect exact preparation request')}</summary><pre>{JSON.stringify(state.prepared?.request ?? original?.input, null, 2)}</pre></details>
        <label className="context-pack-consent"><input type="checkbox" disabled={state.busy || !state.canPrepare} checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
          <span>{t('I confirm these exact original cases, code revisions and target declarations. No build, target execution or test pass is authorized.')}</span></label>
        {state.prepared && !state.stored.attempt && <button type="button" className="small-btn primary" disabled={!state.maySave} onClick={state.save}>{t('Save prepared execution plan')}</button>}
        {original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn primary" disabled={!state.mayConfirmOriginal} onClick={state.confirmOriginal}>{t('Confirm original preparation')}</button>}
      </div>}
      {result && <RunPlanBuildPanel key={`${actorId}:${result.metadata.run_plan_id}:${result.metadata.artifact_hash}`}
        plan={result} actorId={actorId} current={current} onFailure={onFailure} />}
      {result && <RunPlanLocatorPanel key={`locators:${actorId}:${result.metadata.run_plan_id}:${result.metadata.artifact_hash}`}
        plan={result} actorId={actorId} onFailure={onFailure} />}
      {result && <RunPlanLocatorRecordPanel key={`locator-record:${actorId}:${result.metadata.run_plan_id}:${result.metadata.artifact_hash}`}
        plan={result} actorId={actorId} current={current} onFailure={onFailure} />}
      {result && <HttpFixtureRecipePanel key={`fixture-recipe:${actorId}:${result.metadata.run_plan_id}:${result.metadata.artifact_hash}`}
        plan={result} actorId={actorId} current={current} onFailure={onFailure} />}
      {result && result.artifact.plan.proposal.scripts.length > 0 && result.artifact.plan.proposal.scripts.every((v) => v.kind === 'http')
        && <RunPlanCaseExecutionPanel key={`case-execution:${actorId}:${result.metadata.run_plan_id}:${result.metadata.artifact_hash}`}
        plan={result} actorId={actorId} current={current} onFailure={onFailure} />}
      {original && <div className="scope-record"><strong>{t('Original preparation command')}</strong><code>{original.command.id}</code>
        {['pending', 'running'].includes(original.command.status) && <p role="status">{t('The original preparation is still running. It has not been restarted.')}</p>}
        {['failed', 'cancelled'].includes(original.command.status) && <p>{t('The original preparation stopped without a verified plan receipt. It has not been restarted.')}</p>}
      </div>}
      {result && <div className="scope-record" data-testid="prepared-run-plan"><strong>{t('Execution plan prepared; execution remains unauthorized')}</strong>
        <code>{result.metadata.run_plan_id}</code><code>{result.metadata.artifact_hash}</code>
        <p>{t('{cases} original cases and {obligations} obligations retained; executed and passed counts remain zero.', {
          cases: result.artifact.plan.prepared.cases.length, obligations: result.artifact.plan.prepared.obligation_denominator })}</p>
        {!result.current_use.inputs_current && <p>{t('Saved inputs are no longer current. This is an immutable historical plan, not permission to execute.')}</p>}
        <details><summary>{t('Remaining execution gates')}</summary><ul>{result.artifact.plan.remaining_gates.map((gate) => <li key={gate}><code>{gate}</code></li>)}</ul></details>
        <button type="button" className="small-btn" disabled={state.busy} onClick={state.another}>{t('Start another plan declaration')}</button>
      </div>}
    </>}
  </section>
}
