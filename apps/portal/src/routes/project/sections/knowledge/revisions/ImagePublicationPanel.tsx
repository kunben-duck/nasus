import { useImagePublication } from '../../../../../domains/system-image/useImagePublication'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import type { ImageRevisionSummary } from '../../../../../domains/system-image/types/imageRevision'
import type { ImageBaselineOption } from '../../../../../domains/system-image/types/baseline'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import './semantic/semantic-evaluation.css'
import { ImageRollbackPanel } from './ImageRollbackPanel'

export function ImagePublicationPanel({ scope, revision, baselines }: { scope: ImageReadScope; revision: ImageRevisionSummary; baselines: ImageBaselineOption[] }) {
  const { t, tx } = useI18n()
  const state = useImagePublication(scope, revision)
  const view = state.view
  return <><section className="semantic-review" aria-label={t('Image publication')}>
    <button className="small-btn" aria-expanded={state.open} disabled={state.write.isPending} onClick={state.toggle}>{t('Inspect image publication')}</button>
    {state.open && <>
      <p>{t('Publish a fixed knowledge snapshot only. Business expectations, test coverage, generation and release remain separately governed.')}</p>
      <label>{t('Publication target baseline')}<select value={state.baselineId} disabled={state.write.isPending} onChange={(event) => state.choose(event.target.value)}>
        <option value="">{t('Select a target baseline')}</option>
        {baselines.filter((item) => item.project_id === scope.projectId).map((item) => <option key={item.id} value={item.id}>
          {item.kind ? tx(item.kind) : t('Original build target')} · {item.id}</option>)}
      </select></label>
      <button className="small-btn" disabled={!state.baselineId || state.query.isFetching || state.write.isPending} onClick={state.reload}>{t('Reload publication')}</button>
      {state.query.isFetching && <p role="status">{t('Verifying publication, evidence and source access...')}</p>}
      {state.write.isPending && <p role="status">{t('Recording publication decision...')}</p>}
      {state.write.isSuccess && <p role="status">{t('Publication action recorded. Inspect the current head before further changes.')}</p>}
      {(state.query.isError || state.write.isError) && <p role="alert">{state.stale ? t('Publication inputs changed. Reload and review again.')
        : t('Publication was not acknowledged. Reload before retrying; no automatic retry was sent.')}</p>}
      {view && <>
        <div className="semantic-review-head"><strong>{view.head ? t('Published knowledge head') : t('No published knowledge head')}</strong>
          {view.head && <><p><code>{view.head.image_revision_id}</code></p><small>{view.head.actor_id} · {view.head.recorded_at}</small></>}
          <p>{t('Selected image')}: <code>{revision.image_revision_id}</code></p>
          <p>{t('Pinned source manifest')}: <code>{revision.manifest_id}</code></p>
          <p>{t('{count} unverified observations retain their original authority.', { count: view.readiness.unverified_observation_count })}</p>
        </div>
        {view.head?.image_revision_id === revision.image_revision_id ? <p role="status">{t('This exact image is the published knowledge head, not a quality approval.')}</p> : <>
          {view.review && <div className="semantic-review-head"><strong>{view.review.decision === 'approve' ? t('Publication approved') : t('Publication rejected')}</strong>
            <p>{view.review.reason}</p><small>{view.review.actor_id} · {view.review.recorded_at}</small>
            <p>{t('Approval is valid for 30 minutes and only these exact inputs.')}</p></div>}
          {view.can_review ? <fieldset disabled={state.write.isPending || state.write.isError}>
            <legend>{t('Review image publication')}</legend>
            <label>{t('Review decision')}<select value={state.decision} onChange={(event) => state.decide(event.target.value as 'approve' | 'reject')}>
              <option value="approve">{t('Approve publication')}</option><option value="reject">{t('Reject publication')}</option>
            </select></label>
            <label>{t('Review reason')}<textarea rows={2} maxLength={2000} value={state.reason} onChange={(event) => state.explain(event.target.value)} /></label>
            <label className="semantic-confirm"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
              {t('I confirm this exact image, target baseline, current head and review decision.')}</label>
            <button className="small-btn" disabled={!state.canReview} onClick={() => state.submit('review')}>{t('Record publication review')}</button>
            {view.review?.decision === 'approve' && <>
              <label className="semantic-confirm"><input type="checkbox" checked={state.publishConfirmed} onChange={(event) => state.confirmPublish(event.target.checked)} />
                {t('I confirm moving this baseline head to the reviewed image. This does not approve a release.')}</label>
              <button className="small-btn primary" disabled={!state.canPublish} onClick={() => state.submit('publish')}>{t('Publish knowledge snapshot')}</button>
            </>}
          </fieldset> : <p>{t('Only a project administrator can review or publish an image.')}</p>}
        </>}
      </>}
    </>}
  </section><ImageRollbackPanel scope={scope} baselines={baselines} /></>
}
