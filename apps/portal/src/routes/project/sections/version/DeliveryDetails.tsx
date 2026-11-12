import { Link, useSearchParams } from 'react-router-dom'
import { useVersionDelivery } from '../../../../domains/quality-loop/useVersionDelivery'
import type { DeliveryImagePin } from '../../../../domains/quality-loop/types/delivery'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import './delivery.css'
import { ImageRevisionInspector } from '../knowledge/revisions/ImageRevisionInspector'
import { RequirementIntakePanel } from './RequirementIntakePanel'

export function DeliveryDetails({ projectId, versionId }: { projectId: string; versionId: string }) {
  const { t, tx } = useI18n(), { query, view } = useVersionDelivery(projectId, versionId)
  const [params, setParams] = useSearchParams()
  const pinKeys = ['publication_id', 'baseline_id', 'image_revision_id', 'image_artifact_hash'] as const
  const inspecting = pinKeys.some((key) => params.has(key))
  const inspected = view && [view.baseline, view.iteration_image].find((pin) => pin && pinKeys.every((key) =>
    params.getAll(key).length === 1 && params.get(key) === pin[key]))
  function imageHref(pin: DeliveryImagePin) {
    const selection = new URLSearchParams({ version_id: versionId })
    pinKeys.forEach((key) => selection.set(key, pin[key]))
    return `/projects/${encodeURIComponent(projectId)}/versions?${selection}`
  }
  function closeImage() {
    const next = new URLSearchParams(params)
    pinKeys.forEach((key) => next.delete(key))
    setParams(next)
  }
  return <section className="delivery-panel" data-testid="iteration-delivery" aria-label={t('Iteration delivery')}>
    <div className="delivery-toolbar"><h2>{view?.name ?? t('Iteration delivery')}</h2>
      <button type="button" className="small-btn" disabled={query.isFetching} onClick={() => void query.refetch()}>{t('Reload iteration')}</button></div>
    {query.isFetching && <p role="status">{t('Verifying this iteration and its image pins...')}</p>}
    {query.isError && <p role="alert">{t('Iteration could not be verified. Previous content is hidden; reload to check access.')}</p>}
    {view && <>
      <p><code>{view.version_id}</code></p>
      <p>{t('Delivery stage')}: <strong>{t(view.stage === 'image_pinned' ? 'Starting image pinned' : 'Legacy version without a delivery pin')}</strong></p>
      {!view.enabled ? <p>{t('This legacy version has no delivery image binding. No baseline was selected automatically.')}</p> :
        <div className="delivery-pin-grid">
          <DeliveryPin title={t('Immutable starting baseline')} pin={view.baseline!} href={imageHref(view.baseline!)} />
          <DeliveryPin title={t('Current iteration image')} pin={view.iteration_image!} href={imageHref(view.iteration_image!)} />
        </div>}
      <p className="delivery-notice">{t('Image binding is not test completion or release approval. Those decisions remain independently governed.')}</p>
      <h3>{t('Pinned source commits')}</h3>
      {view.code_revisions.length ? <ul className="delivery-evidence">{view.code_revisions.map((source) =>
        <li key={JSON.stringify([source.binding_id, source.source_revision_id])}>
          <span>{source.repository}</span><code>{source.binding_id}</code><code>{source.source_revision_id}</code>
          {source.tracked_ref && <span>{source.tracked_ref}</span>}<code>{source.commit_sha ?? source.external_revision}</code>
        </li>)}</ul> : <p>{t('No source commits recorded for this iteration.')}</p>}
      <h3>{t('Delivery blockers')}</h3>
      {view.blockers.length ? <ul>{view.blockers.map((item) => <li key={item}>{item === 'delivery_m2_not_implemented' ? t('Later delivery stages are not implemented yet.') : tx(item)}</li>)}</ul>
        : <p>{t('No delivery blockers reported. This is not a release verdict.')}</p>}
      <h3>{t('Next independent confirmation')}</h3>
      {view.pending_confirmations.length ? <ol>{view.pending_confirmations.map((item) => <li key={item}>{tx(item)}</li>)}</ol>
        : <p>{t('No pending confirmation reported. Later delivery stages are not completed by this page.')}</p>}
      {view.available_actions.length > 0 && <><h3>{t('Available delivery actions')}</h3>
        <ul>{view.available_actions.map((action) => <li key={action}>{t('View the pinned image')}</li>)}</ul></>}
      <Link to={`/projects/${encodeURIComponent(projectId)}/knowledge`}>{t('Review image publication independently')}</Link>
      {view.enabled && view.iteration_image && <RequirementIntakePanel projectId={projectId} versionId={versionId} image={view.iteration_image} />}
      {inspecting && !inspected && <p role="alert">{t('The selected image pin does not match this iteration. No other image was selected.')}</p>}
      {inspected && <ImageRevisionInspector projectId={projectId} close={closeImage} baselines={[{ id: inspected.baseline_id, project_id: projectId }]}
          pinnedImage={{ project_id: projectId, baseline_id: inspected.baseline_id, image_revision_id: inspected.image_revision_id,
            artifact_hash: inspected.image_artifact_hash, manifest_id: inspected.manifest_id, manifest_hash: inspected.manifest_hash }} />}
    </>}
  </section>
}

function DeliveryPin({ title, pin, href }: { title: string; pin: DeliveryImagePin; href: string }) {
  const { t } = useI18n()
  return <section className="delivery-pin" aria-label={title}><h3>{title}</h3><dl>
    <dt>{t('Publication ID')}</dt><dd>{pin.publication_id}</dd>
    <dt>{t('Baseline ID')}</dt><dd>{pin.baseline_id}</dd>
    <dt>{t('Image revision')}</dt><dd>{pin.image_revision_id}</dd>
    <dt>{t('Artifact hash')}</dt><dd>{pin.image_artifact_hash}</dd>
  </dl><Link className="small-btn" to={href}>{t('View the pinned image')}</Link></section>
}
