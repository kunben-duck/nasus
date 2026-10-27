import { useImageRollback } from '../../../../../domains/system-image/useImageRollback'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import type { ImageBaselineOption } from '../../../../../domains/system-image/types/baseline'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function ImageRollbackPanel({ scope, baselines }: { scope: ImageReadScope; baselines: ImageBaselineOption[] }) {
  const { t, tx } = useI18n(), state = useImageRollback(scope)
  const busy = state.write.isPending, view = state.view
  return <section className="semantic-review" aria-label={t('Image rollback')}>
    <button className="small-btn" aria-expanded={state.open} disabled={busy} onClick={state.toggle}>{t('Inspect image rollback')}</button>
    {state.open && <>
      <p>{t('Restore a previously published knowledge snapshot. Deployment, source revisions and business approvals remain unchanged.')}</p>
      <label>{t('Rollback target baseline')}<select value={state.baselineId} disabled={busy} onChange={(event) => state.baseline(event.target.value)}>
        <option value="">{t('Select a target baseline')}</option>
        {baselines.filter((item) => item.project_id === scope.projectId).map((item) => <option key={item.id} value={item.id}>
          {item.kind ? tx(item.kind) : t('Original build target')} · {item.id}</option>)}
      </select></label>
      <button className="small-btn" disabled={!state.baselineId || state.history.isFetching || busy} onClick={state.reload}>{t('Reload rollback history')}</button>
      {(state.history.isFetching || state.query.isFetching) && <p role="status">{t('Verifying historical publication and archived evidence...')}</p>}
      {busy && <p role="status">{t('Recording rollback action...')}</p>}
      {state.write.isSuccess && <p role="status">{t('Rollback action recorded. Inspect the current head before further changes.')}</p>}
      {state.error && <p role="alert">{state.stale ? t('Publication inputs changed. Reload and review again.') : t('Rollback was not acknowledged. Reload before retrying; no automatic retry was sent.')}</p>}
      {state.page && !state.error && <>
        <p>{t('Current published image')}: <code>{state.page.head?.image_revision_id ?? t('No published knowledge head')}</code></p>
        <label>{t('Historical snapshot')}<select disabled={busy} value={state.selectedId} onChange={(event) => state.choose(event.target.value)}>
          <option value="">{t('Select a historical snapshot')}</option>
          {state.page.items.filter((item) => state.page?.head && item.sequence < state.page.head.sequence && item.image_revision_id !== state.page.head.image_revision_id)
            .map((item) => <option key={item.publication_id} value={item.publication_id}>{item.sequence} · {item.image_revision_id}</option>)}
        </select></label>
        <div className="btn-row">
          <button className="small-btn" disabled={busy || state.after === 0} onClick={() => state.paginate(0)}>{t('First page')}</button>
          <button className="small-btn" disabled={busy || state.page.next_after_sequence === null} onClick={() => state.paginate(state.page?.next_after_sequence ?? 0)}>{t('Next page')}</button>
        </div>
      </>}
      {view && <>
        <div className="semantic-review-head"><strong>{t('Restore this knowledge snapshot')}</strong><p><code>{view.image.image_revision_id}</code></p>
          <p>{t('Pinned source manifest')}: <code>{view.image.manifest_id}</code></p>
          <p>{t('This action preserves all prior publication records and does not restore withdrawn approvals.')}</p></div>
        {view.review && <p>{view.review.decision === 'approve' ? t('Rollback approved') : t('Rollback rejected')}: {view.review.reason}</p>}
        {view.can_review ? <fieldset disabled={busy || state.write.isError}>
          <legend>{t('Review image rollback')}</legend>
          <label>{t('Review decision')}<select value={state.decision} onChange={(event) => state.decide(event.target.value as 'approve' | 'reject')}>
            <option value="approve">{t('Approve rollback')}</option><option value="reject">{t('Reject rollback')}</option>
          </select></label>
          <label>{t('Review reason')}<textarea rows={2} maxLength={2000} value={state.reason} onChange={(event) => state.explain(event.target.value)} /></label>
          <label className="semantic-confirm"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />{t('I confirm this historical snapshot, current head and rollback reason.')}</label>
          <button className="small-btn" disabled={!state.canReview} onClick={() => state.submit('review')}>{t('Record rollback review')}</button>
          {view.review?.decision === 'approve' && <>
            <label className="semantic-confirm"><input type="checkbox" checked={state.restoreConfirmed} onChange={(event) => state.confirmRestore(event.target.checked)} />{t('I confirm restoring knowledge only, without changing deployment or business approvals.')}</label>
            <button className="small-btn primary" disabled={!state.canRestore} onClick={() => state.submit('publish')}>{t('Restore knowledge snapshot')}</button>
          </>}
        </fieldset> : <p>{t('Only a project administrator can review or publish an image.')}</p>}
      </>}
    </>}
  </section>
}
