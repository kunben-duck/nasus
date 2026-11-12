import { Link } from 'react-router-dom'
import type { ProjectRouteContext } from '../../ProjectRouteTypes'
import { useAuthUser } from '../../../../domains/platform/useAuthSession'
import { useIterationCreation } from '../../../../domains/quality-loop/useIterationCreation'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import './delivery.css'

export function VersionCreateSection({ context }: { context: ProjectRouteContext }) {
  const actor = useAuthUser(), { t } = useI18n()
  return <><div className="agent-heading"><h1>{t('Create delivery iteration')}</h1></div>
    {actor.data && !actor.isError ? <IterationForm key={`${context.project.id}:${actor.data.id}`} context={context} actorId={actor.data.id} />
      : <p role="status">{t('Verifying iteration access...')}</p>}</>
}

function IterationForm({ context, actorId }: { context: ProjectRouteContext; actorId: string }) {
  const { t, tx } = useI18n(), projectId = context.project.id, state = useIterationCreation(projectId, actorId)
  const result = state.write.data, attempt = state.attempt
  const baselines = context.systemImage?.baselines.filter((item) => item.project_id === projectId && item.kind === 'official') ?? []
  return <section className="delivery-panel" data-testid="iteration-create" aria-label={t('Create delivery iteration')}>
    <p>{t('Select a published image explicitly. Creating an iteration freezes its starting baseline without approving tests or release.')}</p>
    <div className="delivery-links"><Link to={`/projects/${encodeURIComponent(projectId)}/knowledge`}>{t('Review image publication independently')}</Link>
      <Link to={`/projects/${encodeURIComponent(projectId)}/versions`}>{t('View delivery iterations')}</Link></div>
    {state.storageError && <p role="alert">{t('Iteration recovery storage is unavailable. No new operation was sent.')}</p>}
    {!attempt && <form onSubmit={(event) => { event.preventDefault(); if (state.canCreate) state.execute('submit') }}>
      <fieldset disabled={state.write.isPending || state.storageError}>
        <label>{t('Iteration name')}<input value={state.name} maxLength={200} onChange={(event) => state.setName(event.target.value)} required /></label>
        <label>{t('Starting publication baseline')}<select value={state.baselineId} onChange={(event) => state.chooseBaseline(event.target.value)}>
          <option value="">{t('Select a target baseline')}</option>
          {baselines.map((baseline) => <option key={baseline.id} value={baseline.id}>{tx(baseline.kind)} · {baseline.id}</option>)}
        </select></label>
        {!baselines.length && <p>{t('No official publication baseline is available. Review the image in Knowledge first.')}</p>}
        {state.history.isFetching && <p role="status">{t('Verifying publication, evidence and source access...')}</p>}
        {state.history.isError && <p role="alert">{t('Publication could not be verified. No image was selected automatically.')}</p>}
        {state.baselineId && <button type="button" className="small-btn" disabled={state.history.isFetching}
          onClick={() => void state.history.refetch()}>{t('Reload publication')}</button>}
        {state.head && <label>{t('Explicit published image')}<select value={state.publicationId} onChange={(event) => state.choosePublication(event.target.value)}>
          <option value="">{t('Select a publication')}</option>
          <option value={state.head.publication_id}>{state.head.publication_id} · {state.head.image_revision_id}</option>
        </select></label>}
        {state.history.isSuccess && !state.history.isFetching && !state.head && <p>{t('No published knowledge head')}</p>}
        {state.selected && <div className="delivery-pin"><p><code>{state.selected.publication_id}</code></p>
          <p><code>{state.selected.image_revision_id}</code></p><p><code>{state.selected.image_artifact_hash}</code></p></div>}
        <label className="delivery-consent"><input type="checkbox" checked={state.confirmed} disabled={!state.selected || !state.name.trim()}
          onChange={(event) => state.confirm(event.target.checked)} />{t('I confirm this iteration name and exact published image pin.')}</label>
        <button type="submit" className="small-btn primary" disabled={!state.canCreate}>{t('Create delivery iteration')}</button>
      </fieldset>
    </form>}
    {attempt && <div className="delivery-pin"><h3>{t('Original iteration request')}</h3><p>{attempt.input.name}</p>
      <p><code>{attempt.input.image_binding.publication_id}</code></p><p><code>{attempt.input.image_binding.image_revision_id}</code></p>
      <p><code>{attempt.input.image_binding.image_artifact_hash}</code></p>
      <p>{t('Recovery verifies the original operation. It never selects a newer image or creates a replacement request.')}</p>
      {!result?.delivery && <button type="button" className="small-btn" disabled={state.write.isPending}
        onClick={() => state.execute(attempt.invocation_id ? 'inspect' : 'submit')}>{t('Verify original iteration request')}</button>}
    </div>}
    {state.write.isPending && <p role="status">{t('Verifying iteration creation...')}</p>}
    {state.write.isError && <p role="alert">{t('Iteration creation is unverified. Recover the original request before creating another.')}</p>}
    {result && !result.delivery && <p role="status">{tx(result.receipt.status)} · {tx(result.receipt.summary)}</p>}
    {result?.receipt.status === 'waiting_confirmation' && !state.write.isError && <button type="button" className="small-btn" disabled={state.write.isPending}
      onClick={() => state.execute('confirm')}>{t('Confirm original iteration creation')}</button>}
    {result?.delivery && <p role="status"><Link to={`/projects/${encodeURIComponent(projectId)}/versions?${new URLSearchParams({ version_id: result.delivery.version_id })}`}>
      {t('Open verified iteration')} · {result.delivery.name}</Link></p>}
    {result && (result.delivery || ['failed', 'cancelled'].includes(result.receipt.status)) && <button type="button" className="small-btn" disabled={state.write.isPending}
      onClick={state.reset}>{t('Start a separate iteration request')}</button>}
  </section>
}
