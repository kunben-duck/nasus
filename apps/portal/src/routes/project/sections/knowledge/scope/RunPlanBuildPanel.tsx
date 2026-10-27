import { useRunPlanBuild } from '../../../../../domains/quality-loop/useRunPlanBuild'
import type { RunPlanArchive } from '../../../../../domains/quality-loop/types/runPlans'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { EnvironmentRecordPanel } from './EnvironmentRecordPanel'
import { EnvironmentHealthPanel } from './EnvironmentHealthPanel'

export function RunPlanBuildPanel({ plan, actorId, current, onFailure }: { plan: RunPlanArchive; actorId: string; current: boolean; onFailure: () => void }) {
  const { t } = useI18n(), state = useRunPlanBuild(plan, actorId, current, onFailure)
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Original native build binding')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect original build binding')}</button>
    {state.open && <>
      <p>{t('Bind one original committed build for every code source. This form never builds code, contacts the target or authorizes tests.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload original build binding')}</button>
      {state.busy && <p role="status">{t('Verifying original builds and complete source scope...')}</p>}
      {!state.canBind && <p>{t('The original plan is historical or withdrawn. Saved bindings remain inspectable; new binding is blocked.')}</p>}
      {state.failed && <p role="alert">{t('Original build provenance could not be verified. Protected content is hidden.')}</p>}
      {(state.stored.invalid || state.recovery.isError || (state.write.isError && !state.original)) && <p role="alert">{t('Build binding acknowledgement is unknown. Reload only reads the original command and never resends the write.')}</p>}
      {!state.stored.attempt && !state.stored.invalid && state.canBind && <fieldset disabled={!state.editable}>
        <legend>{t('Complete original native builds')}</legend>
        {state.code.map((source) => <div className="scope-record" key={source.binding_id}>
          <code>{source.binding_id}</code><code>{source.source_revision_id}</code>
          <label>{t('Original build command ID')}<input aria-label={`${t('Original build command ID')} ${source.binding_id}`} value={state.ids[source.binding_id]}
            maxLength={128} autoComplete="off" onChange={(event) => state.editId(source.binding_id, event.target.value)} /></label>
        </div>)}
        <label>{t('Primary target build')}<select aria-label={t('Primary target build')} value={state.target} onChange={(event) => state.editTarget(event.target.value)}>
          <option value="">{t('Choose an original build explicitly')}</option>
          {state.code.filter((s) => state.ids[s.binding_id].trim()).map((s) => <option value={state.ids[s.binding_id].trim()} key={s.binding_id}>{s.binding_id}</option>)}
        </select></label>
        <label>{t('Build binding reason')}<textarea aria-label={t('Build binding reason')} value={state.reason} maxLength={4096} onChange={(event) => state.editReason(event.target.value)} /></label>
      </fieldset>}
      {!state.stored.attempt && <button type="button" className="small-btn" disabled={!state.mayPreview} onClick={state.preview}>{t('Verify builds and preview binding')}</button>}
      {state.verify.isError && <p role="alert">{t('Build binding preview was rejected. Verify every original command, code revision, artifact and root build definition.')}</p>}
      {(state.prepared || state.original?.command.status === 'waiting_confirmation') && <div className="scope-record">
        <details><summary>{t('Inspect exact build binding request')}</summary><pre>{JSON.stringify(state.prepared?.value.request ?? state.original?.input, null, 2)}</pre></details>
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.canBind} onChange={(event) => state.confirm(event.target.checked)} />
          <span>{t('I independently confirm this original plan and every native build. Environment, fixtures and target execution remain unverified and unauthorized.')}</span></label>
        {state.prepared && !state.stored.attempt && <button type="button" className="small-btn primary" disabled={!state.maySave} onClick={state.save}>{t('Save original build binding')}</button>}
        {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn primary" disabled={!state.mayConfirmOriginal} onClick={state.confirmOriginal}>{t('Confirm original build binding')}</button>}
      </div>}
      {state.original && <div className="scope-record"><strong>{t('Original build binding command')}</strong><code>{state.original.command.id}</code><code>{state.original.command.status}</code></div>}
      {state.result && <div className="scope-record" data-testid="original-build-binding">
        <strong>{t('Original builds bound; target execution remains unauthorized')}</strong><code>{state.result.metadata.binding_id}</code><code>{state.result.metadata.artifact_hash}</code>
        <p>{t('{sources} original code sources verified; executed and passed counts remain zero.', { sources: state.result.artifact.binding.builds.length })}</p>
        {!state.result.current_use.inputs_current && <p>{t('Saved inputs are no longer current. This is an immutable historical plan, not permission to execute.')}</p>}
        <details><summary>{t('Remaining execution gates')}</summary><ul>{state.result.artifact.binding.remaining_gates.map((gate) => <li key={gate}><code>{gate}</code></li>)}</ul></details>
        <EnvironmentRecordPanel key={JSON.stringify([actorId, state.result.metadata.binding_id, state.result.metadata.artifact_hash])}
          plan={plan} binding={state.result} actorId={actorId} current={current} onFailure={onFailure} />
        <EnvironmentHealthPanel key={'health:' + JSON.stringify([actorId, state.result.metadata.binding_id, state.result.metadata.artifact_hash])}
          plan={plan} binding={state.result} actorId={actorId} current={current} onFailure={onFailure} />
        <button type="button" className="small-btn" disabled={state.busy} onClick={state.another}>{t('Inspect another build binding')}</button>
      </div>}
    </>}
  </section>
}
