import { useEffect, useId, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { prepareSourceRefresh, refreshableSources, sourceRefreshApi, sourceRefreshScope, type SourceRefreshAttempt } from '../../../../../domains/system-image/sourceRefreshApi'
import { useWorkingImage } from '../../../../../domains/system-image/useWorkingImage'
import { sourceRefreshRecovery } from '../../../../../domains/system-image/sourceRefreshRecovery'
import { hasAuthToken, useAuthUser } from '../../../../../domains/platform/useAuthSession'
import type { ToolInvocation } from '../../../../../domains/platform/types'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import '../evidence-inspector.css'
import './source-refresh.css'

const sourceLabels = { code: 'Code repository', us_doc: 'Historical US documents', test_asset: 'Historical test assets' } as const

export function SourceRefreshInspector({ projectId, close }: { projectId: string; close: () => void }) {
  const user = useAuthUser()
  return user.data && !user.isError && hasAuthToken()
    ? <AccountSourceRefreshInspector key={JSON.stringify([user.data.id, projectId])}
      actorId={user.data.id} projectId={projectId} close={close} /> : null
}

function AccountSourceRefreshInspector({ actorId, projectId, close }: { actorId: string; projectId: string; close: () => void }) {
  const { t, tx } = useI18n(), titleId = useId(), client = useQueryClient()
  const query = useWorkingImage(projectId, titleId)
  const dialog = useRef<HTMLDialogElement>(null), active = useRef(false), busy = useRef(false)
  const recovery = useRef<AbortController | null>(null)
  const [selection, setSelection] = useState<{ scope: string; ids: string[] }>({ scope: '', ids: [] })
  const [initialRecord] = useState(() => sourceRefreshRecovery.read(actorId, projectId))
  const [attempt, setAttempt] = useState<SourceRefreshAttempt | null>(() => initialRecord.status === 'saved' ? initialRecord.attempt : null)
  const [storageBlocked, setStorageBlocked] = useState(initialRecord.status === 'invalid' || initialRecord.status === 'unavailable')
  const [restored, setRestored] = useState(initialRecord.status === 'saved')
  const [command, setCommand] = useState<ToolInvocation | null>(null)
  const [pending, setPending] = useState(false), [failed, setFailed] = useState(false)
  useEffect(() => {
    const element = dialog.current!, opener = document.activeElement
    active.current = true
    element.showModal()
    return () => {
      active.current = false
      recovery.current?.abort()
      element.close()
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [])
  let sources: ReturnType<typeof refreshableSources> = [], verified = false, scope = ''
  try {
    if (query.data && !query.isError && !query.isFetching) {
      sources = refreshableSources(projectId, query.data)
      scope = sourceRefreshScope(projectId, query.data)
      verified = true
    }
  } catch { /* Do not display an unverified source scope. */ }
  // A read of the same frozen scope must not discard a user's choice. A failed
  // read or changed scope must not restore consent when the old scope reappears.
  if (selection.scope && !query.isFetching && (!verified || selection.scope !== scope)) {
    setSelection({ scope: '', ids: [] })
  }
  const ids = attempt?.input.source_ids ?? (selection.scope === scope ? selection.ids : [])
  const terminal = command && ['completed', 'failed', 'cancelled'].includes(command.status)

  async function run(recover: boolean) {
    if (busy.current || (!recover && (storageBlocked || !verified || !query.data || attempt || !ids.length))) return
    let fixed = attempt
    if (!recover) {
      try {
        fixed = { input: prepareSourceRefresh(projectId, query.data!, ids), requestKey: crypto.randomUUID() }
        // Persist the recovery pointer before dispatch; storage failure must not send a write.
        sourceRefreshRecovery.save(actorId, fixed)
      } catch { setStorageBlocked(true); return }
      setAttempt(fixed)
    }
    if (!fixed) return
    busy.current = true
    setPending(true)
    setFailed(false)
    const controller = recover ? new AbortController() : null
    recovery.current = controller
    try {
      const result = controller ? await sourceRefreshApi.recover(fixed, controller.signal)
        : await sourceRefreshApi.submit(fixed)
      const acknowledged = { ...fixed, commandId: result.id }
      sourceRefreshRecovery.acknowledge(actorId, acknowledged)
      if (!active.current) return
      setAttempt(acknowledged)
      setStorageBlocked(false)
      setCommand(result)
      if (['completed', 'failed', 'cancelled'].includes(result.status)) {
        // Refresh read models only. Do not execute any suggested build or publication tool.
        void client.invalidateQueries({ queryKey: ['system-image', projectId] }).catch(() => undefined)
      }
    } catch {
      if (active.current) setFailed(true)
    } finally {
      if (recovery.current === controller) recovery.current = null
      busy.current = false
      if (active.current) setPending(false)
    }
  }

  function reload() {
    if (busy.current || (attempt && !terminal)) return
    try {
      if (attempt) sourceRefreshRecovery.clear(actorId, attempt)
      const record = sourceRefreshRecovery.read(actorId, projectId)
      if (record.status === 'invalid' || record.status === 'unavailable') { setStorageBlocked(true); return }
      setAttempt(record.status === 'saved' ? record.attempt : null)
      setRestored(record.status === 'saved')
      setStorageBlocked(false)
      setSelection({ scope: '', ids: [] }); setCommand(null); setFailed(false)
      void query.refetch()
    } catch { setStorageBlocked(true) }
  }

  return <dialog ref={dialog} className="evidence-inspector source-refresh-inspector" aria-labelledby={titleId} onCancel={close}>
    <header><div><span className="eyebrow">{t('System image')}</span><h2 id={titleId}>{t('Refresh working sources')}</h2></div>
      <button type="button" onClick={close}>{t('Close')}</button></header>
    <div className="evidence-inspector-body">
      <p>{t('Only selected registered sources will be collected again. Existing images, approvals and test results stay unchanged; building and publishing require separate actions.')}</p>
      <button type="button" disabled={pending || Boolean(attempt && !terminal)} onClick={reload}>{t('Reload working sources')}</button>
      {storageBlocked && <p role="alert">{t('The local refresh recovery record could not be verified. No new refresh was sent. Restore browser storage access and reload; an existing request must not be discarded.')}</p>}
      {!verified ? <p role={query.isError || (!query.isFetching && query.data) ? 'alert' : 'status'}>
        {t(query.isFetching ? 'Loading working draft...' : 'Working sources could not be verified. Previous content is hidden; reload to check access.')}</p>
        : <>
          <details className="evidence-integrity-details"><summary>{t('Source manifest')}</summary>
            <p>{query.data!.source_manifest!.manifest_id}</p><p>{query.data!.source_manifest!.content_hash}</p></details>
          {!sources.length && <p>{t('Register and capture a code source before refreshing selected sources.')}</p>}
          <ul className="source-refresh-list" aria-label={t('Registered working sources')}>
            {sources.map((source) => <li key={source.id} data-source-id={source.id}>
              <label><input type="checkbox" checked={ids.includes(source.id)} disabled={pending || storageBlocked || Boolean(attempt)}
                onChange={(event) => setSelection({ scope,
                  ids: event.target.checked ? [...ids, source.id] : ids.filter((value) => value !== source.id) })} />
                <span><strong>{source.source_label || t(sourceLabels[source.source_type])}</strong><small>{source.id}</small>
                  <small>{tx(source.ingestion_status)}</small></span></label>
            </li>)}
          </ul>
          <p>{t('{count} sources selected', { count: ids.length })}</p>
          {ids.length > 100 && <p role="alert">{t('Select no more than 100 sources per refresh.')}</p>}
          <button type="button" disabled={pending || storageBlocked || Boolean(attempt) || !ids.length || ids.length > 100}
            onClick={() => { void run(false) }}>{t(pending ? 'Refreshing sources...' : 'Refresh selected sources')}</button>
        </>}
      {attempt && <div className="source-refresh-command" role="status">
        {restored && <p>{t('An earlier refresh request was found in this tab. Check its original command before making another selection. No refresh was resent.')}</p>}
        <p>{t('Original refresh request')}: {attempt.requestKey}</p>
        {command && <p>{t('Tool invocation')}: {command.id} · {tx(command.status)}</p>}
        {command?.status === 'completed' && <p>{t('Selected sources were refreshed. Review the new source manifest before preparing a separately confirmed build.')}</p>}
        {command?.status === 'failed' && <p>{t('Source refresh failed. Inspect the source state and reload before making a new selection.')}</p>}
        {failed && <p role="alert">{t('The original refresh acknowledgement could not be verified. Check the original command; do not resend it.')}</p>}
        {!terminal && <button type="button" disabled={pending} onClick={() => { void run(true) }}>{t('Check original refresh command')}</button>}
      </div>}
    </div>
  </dialog>
}
