import { useStructureBuild } from '../../../../../domains/system-image/useStructureBuild'
import type { BuildPlan } from '../../../../../domains/system-image/types/buildPlan'
import type { BaselineRecord } from '../../../../../domains/system-image/types/baseline'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function StructureBuildAction({ scope, plan, baselines }: { scope: ImageReadScope; plan: BuildPlan; baselines: BaselineRecord[] }) {
  const { t } = useI18n()
  const { target, setTarget, invocation, running, locked, busy, checking, statusFailed, reloadStatus, unacknowledged, failed,
    unfinished, restore, more, hasMore, execute, cancellation, cancelled } = useStructureBuild(scope, plan)
  const code = plan.proposal.intent.sources.filter((source) => source.source_type === 'code')
  const ready = code.length > 0 && code.every((source) => source.status === 'captured')
  return <div className="build-plan-form structure-build-action">
    <h3>{t('Build pinned structure')}</h3>
    <p>{t('One confirmed structural task only: archived inputs, no model calls, no repository execution and no publication.')}</p>
    {unfinished.length > 0 && <label>{t('Unfinished structural command')}<select value="" disabled={checking} onChange={(event) => restore(event.target.value)}>
      <option value="">{t('Select an unfinished command to resume')}</option>
      {unfinished.map((item) => <option key={item.invocation_id} value={item.invocation_id}>{item.status} · {item.target_baseline_id} · {item.invocation_id}</option>)}
    </select></label>}
    {hasMore && <button type="button" disabled={checking} onClick={() => void more()}>{t('Load more structural commands')}</button>}
    <label>{t('Candidate target baseline')}<select value={target} disabled={locked} onChange={(event) => setTarget(event.target.value)}>
      <option value="">{t('Select a target baseline')}</option>
      {baselines.filter((item) => item.project_id === scope.projectId && (!plan.proposal.intent.target || item.id === plan.proposal.intent.target.target_baseline_id))
        .map((item) => <option key={item.id} value={item.id}>{item.kind} · {item.id}</option>)}
    </select></label>
    {invocation && <p role="status">{t('Confirm this plan digest and target. Only its structural task will run, within {seconds} seconds.', { seconds: plan.proposal.intent.budget.max_active_seconds })}</p>}
    {running && <p role="status">{t('Building structure...')}</p>}
    {!ready && <p>{t('Capture every required code source before building structure.')}</p>}
    <button type="button" disabled={!ready || !target || busy || checking || statusFailed} onClick={() => void execute()}>
      {busy ? t('Building structure...') : invocation ? t('Confirm structural build') : t('Prepare structural build')}</button>
    {failed && <p role="alert">{t('Structural build did not complete. Check access, target and budget; saved candidates are retained.')}</p>}
    {cancelled && <p role="status">{t('Structural build was cancelled. Saved candidates are retained.')}</p>}
    {cancellation.visible && <section aria-label={t('Stop structural build')}>
      {cancellation.requested ? <p role="status">{t('Stop requested. Waiting for the worker to exit; saved candidates are retained.')}</p> : <>
        <label className="structure-stop-consent"><input type="checkbox" checked={cancellation.checked} disabled={cancellation.busy || cancellation.error || cancellation.checking}
          onChange={(event) => cancellation.check(event.target.checked)} />{t('Confirm stopping this exact structural command')}</label>
        <button type="button" disabled={!cancellation.canCancel} onClick={() => void cancellation.cancel()}>{t('Stop structural build')}</button>
      </>}
      {cancellation.error && <><p role="alert">{t('Stop outcome could not be verified. Reload before another action; no automatic retry was sent.')}</p>
        <button type="button" disabled={cancellation.busy || cancellation.checking} onClick={() => void cancellation.reload()}>{t('Reload stop status')}</button></>}
    </section>}
    {unacknowledged && <p role="alert">{t('Structural command was not acknowledged. Retry the same request to check its outcome; no automatic retry was sent.')}</p>}
    {statusFailed && <><p role="alert">{t('Structural command status could not be verified. Reload status before another action.')}</p>
      <button type="button" disabled={checking} onClick={() => void reloadStatus()}>{t('Reload structural status')}</button></>}
    {plan.structural_artifacts.length > 0 && <section aria-label={t('Recent structural candidates')}>
      <h3>{t('Recent structural candidates')}</h3><ul className="image-revision-rows">{plan.structural_artifacts.map((item) => <li key={item.invocation_id}>
        <strong>{t('Candidate only')}</strong><p>{item.image_revision_id}</p><p>{item.target_baseline_id}</p><p>{item.confirmed_at}</p>
      </li>)}</ul></section>}
  </div>
}
