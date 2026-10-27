import { useAuthUser } from '../../../../../domains/platform/useAuthSession'
import { useContextAuthorityRegistration } from '../../../../../domains/system-image/useContextAuthorityRegistration'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import '../scope/test-design-scope.css'
import './context-authority-registration.css'

export function ContextAuthorityRegistrationQueue({ projectId }: { projectId: string }) {
  const user = useAuthUser()
  if (!user.data || user.isError || user.isFetching) return null
  return <RegistrationQueue key={`${projectId}:${user.data.id}`} projectId={projectId} sessionId={user.data.id} />
}

function RegistrationQueue({ projectId, sessionId }: { projectId: string; sessionId: string }) {
  const { t } = useI18n(), state = useContextAuthorityRegistration(projectId, sessionId)
  const busy = state.list.isFetching || state.write.isPending
  return <section className="test-design-scope context-authority-registration" aria-label={t('Historical context dependencies')}>
    <button type="button" aria-expanded={state.open} disabled={state.write.isPending} onClick={state.toggle}>{t('Inspect historical context dependencies')}</button>
    {state.open && <>
      <p>{t('Register original dependency versions for migrated contexts. This does not approve requirements, update old answers or clear stale state.')}</p>
      <button type="button" disabled={busy} onClick={state.reload}>{t('Reload dependency queue')}</button>
      {busy && <p role="status">{t('Verifying original context archives and current source permissions...')}</p>}
      {state.failed && <p role="alert">{t('Dependency registration could not be verified. Protected selections are hidden. Reload to inspect the outcome before another confirmation.')}</p>}
      {state.write.isSuccess && <p role="status">{t('Original dependencies registered. Reload any previously blocked context view; its approval and stale state are unchanged.')}</p>}
      {state.rows && <>
        {!state.rows.length && <p>{t('No historical contexts need dependency registration.')}</p>}
        <div className="context-authority-options">{state.rows.map((item) => <button type="button" key={item.registration_request.context_id}
          aria-pressed={state.item?.registration_request.context_id === item.registration_request.context_id}
          onClick={() => state.choose(item.registration_request.context_id)}>{t('Inspect context {id}', { id: item.registration_request.context_id })}</button>)}</div>
        <div className="scope-actions">
          <button type="button" disabled={!state.previous} onClick={state.previous}>{t('Previous page')}</button>
          <button type="button" disabled={!state.next} onClick={state.next}>{t('Next page')}</button>
        </div>
      </>}
      {state.item && <div className="scope-record">
        <strong>{t('Original context')}</strong><code>{state.item.registration_request.context_id}</code>
        <strong>{t('Image revision')}</strong><code>{state.item.image_revision_id}</code>
        <strong>{t('Artifact hash')}</strong><code>{state.item.registration_request.artifact_hash}</code>
        <label className="context-authority-consent"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
          <span>{t('I confirm registration of this exact historical context and its original dependency versions, without changing approvals or execution permissions.')}</span></label>
        <button type="button" disabled={!state.confirmed} onClick={state.save}>{t('Register original dependencies')}</button>
      </div>}
    </>}
  </section>
}
