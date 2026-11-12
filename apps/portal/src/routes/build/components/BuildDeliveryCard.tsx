import { Link } from 'react-router-dom'
import type { ConversationSession } from '../../../domains/agent/types'
import { deliveryConversationState } from '../../../domains/quality-loop/deliveryConversation'
import { useVersionDelivery } from '../../../domains/quality-loop/useVersionDelivery'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import '../../project/sections/version/delivery.css'

export function BuildDeliveryCard({ conversation, reviewHref, sendPrompt, busy }: {
  conversation: ConversationSession; reviewHref?: string; sendPrompt: (content: string) => Promise<void>; busy: boolean
}) {
  const { t, locale } = useI18n(), { proposal, versionId } = deliveryConversationState(conversation)
  const projectId = conversation.project_id
  if (!projectId) return null
  const root = `/projects/${encodeURIComponent(projectId)}`
  return <section className="build-progress delivery-panel" data-testid="build-delivery-card" aria-label={t('Image publication and delivery')}>
    <strong>{t('Image publication and delivery')}</strong>
    <p>{t('Project setup, source capture, candidate analysis, image publication and delivery iterations are separate stages.')}</p>
    <div className="delivery-links"><Link to={reviewHref ?? `${root}/knowledge`}>{t('Review image publication independently')}</Link>
      <Link to={`${root}/versions/create`}>{t('Create delivery iteration')}</Link><Link to={`${root}/versions`}>{t('View delivery iterations')}</Link></div>
    {proposal && <div className="delivery-pin" data-testid="build-delivery-proposal"><h3>{t('Saved iteration proposal')}</h3>
      <p>{proposal.name || t('Choose an iteration name')}</p>
      {proposal.publication_id && <p><code>{proposal.publication_id}</code></p>}
      {proposal.image_binding && <><p><code>{proposal.image_binding.image_revision_id}</code></p><p><code>{proposal.image_binding.image_artifact_hash}</code></p></>}
      {proposal.stage === 'selection' && <p>{t('Choose a name and an explicit publication ID. No latest image will be selected for you.')}</p>}
      {proposal.stage === 'confirmation' && <><p>{t('Confirming creates only this pinned iteration. Publication, tests and release require separate decisions.')}</p>
        <button type="button" className="small-btn" disabled={busy} onClick={() => void sendPrompt(locale === 'zh' ? '确认创建迭代' : 'confirm iteration creation')}>
          {t('Confirm original iteration creation')}</button></>}
    </div>}
    {versionId && <BuildIterationProgress key={`${projectId}:${versionId}`} projectId={projectId} versionId={versionId} />}
  </section>
}

function BuildIterationProgress({ projectId, versionId }: { projectId: string; versionId: string }) {
  const { t } = useI18n(), { query, view } = useVersionDelivery(projectId, versionId)
  return <div data-testid="build-iteration-progress">
    {query.isFetching && <p role="status">{t('Verifying this iteration and its image pins...')}</p>}
    {query.isError && <p role="alert">{t('Iteration could not be verified. Previous content is hidden; reload to check access.')}</p>}
    <button type="button" className="small-btn" disabled={query.isFetching} onClick={() => void query.refetch()}>{t('Reload iteration')}</button>
    {view && <><p>{view.name} · {t(view.enabled ? 'Starting image pinned' : 'Legacy version without a delivery pin')}</p>
      <p>{t('Image binding is not test completion or release approval. Those decisions remain independently governed.')}</p>
      <Link to={`/projects/${encodeURIComponent(projectId)}/versions?${new URLSearchParams({ version_id: versionId })}`}>{t('Open verified iteration')}</Link></>}
  </div>
}
