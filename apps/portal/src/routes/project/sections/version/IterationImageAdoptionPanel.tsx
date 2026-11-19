import { useAuthUser } from '../../../../domains/platform/useAuthSession'
import { useIterationImageAdoption } from '../../../../domains/quality-loop/useIterationImageAdoption'
import type { VersionDelivery } from '../../../../domains/quality-loop/types/delivery'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function IterationImageAdoptionPanel({ view }: { view: VersionDelivery }) {
  const actor = useAuthUser()
  return actor.data && !actor.isError ? <Adoption key={`${view.version_id}:${view.iteration_image?.image_revision_id}:${actor.data.id}`} view={view} actorId={actor.data.id} /> : null
}

function Adoption({ view, actorId }: { view: VersionDelivery; actorId: string }) {
  const { t } = useI18n(), state = useIterationImageAdoption(view, actorId)
  const rows = !state.history.isError ? state.history.data?.pages.flatMap((page) => page.items) : undefined
  return <section className="delivery-panel" data-testid="iteration-image-adoption">
    <button type="button" className="small-btn" disabled={state.busy} onClick={() => state.setOpen(!state.open)}>{t('Adopt a working image')}</button>
    {state.open && <>
      <p>{t('The initial baseline stays unchanged. A new code image requires requirement review and new downstream approvals.')}</p>
      <label>{t('Image revision')}<select value={state.selected} disabled={state.busy || state.history.isFetching}
        onChange={(event) => { state.setSelected(event.target.value); state.confirm(false) }}>
        <option value="">{t('Select an image revision')}</option>
        {rows?.filter((item) => item.image_revision_id !== view.iteration_image?.image_revision_id).map((item) =>
          <option key={item.image_revision_id} value={item.image_revision_id}>{item.recorded_at} · {item.image_revision_id}</option>)}
      </select></label>
      {state.history.hasNextPage && <button type="button" className="small-btn" disabled={state.history.isFetching} onClick={() => void state.history.fetchNextPage()}>{t('Next')}</button>}
      {state.option.isFetching && <p role="status">{t('Verifying this iteration and its image pins...')}</p>}
      {(state.history.isError || state.option.isError) && <p role="alert">{t('This image cannot be adopted. Check source access, repository bindings and the current iteration.')}</p>}
      {state.preview && <>
        <ul className="delivery-evidence">{state.preview.code_revisions.map((item) => <li key={item.binding_id}><span>{item.repository}</span>
          <code>{view.code_revisions.find((old) => old.binding_id === item.binding_id)?.commit_sha} → {item.commit_sha}</code></li>)}</ul>
        <label>{t('Reason')}<textarea value={state.reason} maxLength={2000} disabled={state.busy} onChange={(event) => { state.setReason(event.target.value); state.confirm(false) }} /></label>
        <label><input type="checkbox" checked={state.confirmed} disabled={state.busy || !state.reason.trim()} onChange={(event) => state.confirm(event.target.checked)} />
          {t('I confirm these commits and understand that previous approvals cannot be reused.')}</label>
        <button type="button" className="small-btn primary" disabled={state.busy || !state.confirmed} onClick={() => void state.adopt()}>{t('Confirm image adoption')}</button>
      </>}
      {state.error && <p role="alert">{t('Adoption could not be verified. Inspect the original command before retrying.')}</p>}
    </>}
  </section>
}
