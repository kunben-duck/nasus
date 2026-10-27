import { useAuthUser } from '../../../../../domains/platform/useAuthSession'
import { useNativeBuild } from '../../../../../domains/quality-loop/useNativeBuild'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import type { ImageRevisionSummary } from '../../../../../domains/system-image/types/imageRevision'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import '../scope/run-plan.css'
import { NativeBuildCancellationPanel } from './NativeBuildCancellationPanel'

export function NativeBuildPanel({ scope, revision }: { scope: ImageReadScope; revision: ImageRevisionSummary }) {
  const actor = useAuthUser()
  if (!actor.data || actor.isError) return null
  return <NativeBuildContent key={JSON.stringify([scope.projectId, scope.sessionId, actor.data.id, revision.image_revision_id, revision.artifact_hash])}
    scope={scope} revision={revision} actorId={actor.data.id} />
}
function NativeBuildContent({ scope, revision, actorId }: { scope: ImageReadScope; revision: ImageRevisionSummary; actorId: string }) {
  const { t, tx } = useI18n(), state = useNativeBuild(scope, revision, actorId)
  return <section className="run-plan-panel test-design-mapping" aria-label={t('Fixed-source native build')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect fixed-source native build')}</button>
    {state.open && <>
      <p>{t('Build one exact code revision with the operator-configured offline Java 21 and Maven 3.9.11 toolchain. This does not run tests or verify business coverage.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload original native build')}</button>
      {state.busy && <p role="status">{t('Verifying original native build and source access...')}</p>}
      {state.failed && <p role="alert">{t('Original build provenance could not be verified. Protected content is hidden.')}</p>}
      {(state.stored.invalid || state.recovery.isError || state.write.isError && !state.original) && <p role="alert">{t('Native build acknowledgement is unknown. Reload only reads the original command; it never rebuilds or confirms automatically.')}</p>}
      {!state.stored.attempt && !state.stored.invalid && !state.failed && <fieldset disabled={!state.editable}>
        <legend>{t('Original Maven build inputs')}</legend>
        <label>{t('Frozen code source')}<select aria-label={t('Frozen code source')} value={state.binding} onChange={(event) => state.edit('binding', event.target.value)}>
          <option value="">{t('Choose a frozen code source explicitly')}</option>
          {state.code.map((s) => <option key={s.binding_id} value={s.binding_id}>{s.binding_id} · {s.source_revision_id}</option>)}
        </select></label>
        <label>{t('Target JAR path')}<input aria-label={t('Target JAR path')} value={state.path} maxLength={1024} autoComplete="off" placeholder={t('For example, target/application.jar')} onChange={(event) => state.edit('path', event.target.value)} /></label>
        <label>{t('Expected JAR SHA-256 (optional)')}<input aria-label={t('Expected JAR SHA-256 (optional)')} value={state.expected} maxLength={71} autoComplete="off" onChange={(event) => state.edit('expected', event.target.value)} /></label>
        <button type="button" className="small-btn" disabled={!state.mayPreview} onClick={state.verify}>{t('Preview exact native build')}</button>
      </fieldset>}
      {state.preview.isError && <p role="alert">{t('Native build preview was rejected. Check the exact code revision, root pom.xml, current administrator access and operator toolchain configuration.')}</p>}
      {(state.prepared || state.original?.command.status === 'waiting_confirmation') && <div className="scope-record">
        <details><summary>{t('Inspect exact native build request')}</summary><pre>{JSON.stringify(state.prepared?.value ?? state.originalPrepared?.value ?? state.original?.input, null, 2)}</pre></details>
        {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn" disabled={state.busy} onClick={state.verifyOriginal}>{t('Verify original build policy again')}</button>}
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.prepared && !state.originalPrepared} onChange={(event) => state.confirm(event.target.checked)} />
          <span>{t('I independently authorize building this exact source with the displayed offline toolchain. This does not authorize target execution or approve requirements, tests or release.')}</span></label>
        {state.prepared && !state.stored.attempt && <button type="button" className="small-btn primary" disabled={!state.maySave} onClick={state.save}>{t('Start confirmed native build')}</button>}
        {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn primary" disabled={!state.mayConfirmOriginal} onClick={state.confirmOriginal}>{t('Confirm original native build')}</button>}
      </div>}
      {state.original && <div className="scope-record" data-testid="native-build-original-command"><strong>{t('Original build command ID')}</strong><code>{state.original.command.id}</code><span>{tx(state.original.command.status)}</span></div>}
      {state.original && <NativeBuildCancellationPanel key={state.original.command.id} scope={scope} actorId={actorId}
        targetId={state.original.command.id} input={state.original.input} status={state.original.command.status}
        sourceRead={state.sourceRead} reloadTarget={state.reload} />}
      {state.original?.view?.metadata === null && <p>{state.original.view.outcome_unknown
        ? t('A native build was reserved but its output is unknown. Automatic rebuilding is blocked; inspect the original worker and cleanup before any new attempt.')
        : t('No original build artifact has been committed. This status is not a successful build or a test result.')}</p>}
      {state.complete?.metadata && <div className="scope-record" data-testid="native-build-original-artifact">
        <strong>{t('Original build artifact verified; tests have not run')}</strong><code>{state.complete.metadata.build_id}</code>
        <code>{state.complete.receipt.artifact.path}</code><code>{state.complete.receipt.artifact.content_hash}</code>
        <p>{t('{files} original files · {bytes} artifact bytes · executed and passed counts remain zero.', { files: state.complete.receipt.source.files.length, bytes: state.complete.receipt.artifact.byte_count })}</p>
        <details><summary>{t('Inspect original source and toolchain receipt')}</summary><pre>{JSON.stringify(state.complete.receipt, null, 2)}</pre></details>
        <p>{t('Use this original command and artifact hash when preparing and binding an execution plan. Reproducibility, environment, fixtures and release remain unverified.')}</p>
      </div>}
      {state.mayStartAnother && <button type="button" className="small-btn" onClick={state.another}>{t('Prepare another independently confirmed build')}</button>}
    </>}
  </section>
}
