import { useState } from 'react'
import type { ProjectRouteContext } from '../ProjectRouteTypes'
import type { SystemImageKnowledgeCardView } from '../ProjectSectionViewModels'
import { knowledgeSectionModel } from '../ProjectSectionViewModels'
import { MetricMini } from './primitives/MetricCards'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { EvidenceInspector } from './knowledge/EvidenceInspector'
import { SourceVisibilityNotice } from '../../../shared/ui/SourceVisibilityNotice'
import { AnalysisInspector } from './knowledge/analysis/AnalysisInspector'
import { WorkingImageInspector } from './knowledge/WorkingImageInspector'
import { PublishedContextPanel } from './knowledge/PublishedContextPanel'
import { FrozenIndexPanel } from './knowledge/FrozenIndexPanel'
import { TestDesignReviewQueue } from './knowledge/scope/TestDesignReviewQueue'
import { HttpFixtureHistoryPanel } from './knowledge/scope/HttpFixtureHistoryPanel'
import { ContextAuthorityRegistrationQueue } from './knowledge/revisions/ContextAuthorityRegistrationQueue'
import { BuildReviewNavigation } from './knowledge/revisions/BuildReviewNavigation'
import { SourceRefreshInspector } from './knowledge/sources/SourceRefreshInspector'

export function KnowledgeSection({ context, objectId }: { context: ProjectRouteContext; objectId?: string }) {
  const { t, tx } = useI18n()
  const model = knowledgeSectionModel(context, objectId)
  const [inspected, setInspected] = useState<{ projectId: string; objectId: string } | null>(null)
  const [analysisProjectId, setAnalysisProjectId] = useState<string | null>(null)
  const [revisionProjectId, setRevisionProjectId] = useState<string | null>(null)
  const [planProjectId, setPlanProjectId] = useState<string | null>(null)
  const [sourceProjectId, setSourceProjectId] = useState<string | null>(null)
  if (sourceProjectId && (sourceProjectId !== context.projectId || !context.systemImage)) setSourceProjectId(null)
  if (planProjectId && (planProjectId !== context.projectId || !context.systemImage)) setPlanProjectId(null)
  if (analysisProjectId && (analysisProjectId !== context.projectId || !context.systemImage)) setAnalysisProjectId(null)
  if (revisionProjectId && (revisionProjectId !== context.projectId || !context.systemImage)) setRevisionProjectId(null)
  const inspectedObject = context.systemImage && inspected?.projectId === context.projectId
    ? model.objects.find((object) => object.id === inspected?.objectId) : undefined
  // Once access or the snapshot is lost, restoring it must not reopen old evidence.
  if (inspected && !inspectedObject) setInspected(null)

  if (context.reviewingBuild && context.projectId) return <BuildReviewNavigation projectId={context.projectId} />

  if (!context.systemImage) return <p role={context.systemImageError ? 'alert' : 'status'}>{context.systemImageError
    ? t('System image could not be verified. Reload to check access; previous knowledge is hidden.')
    : t('Loading system image...')}</p>

  return (
    <>
      <div className="agent-heading knowledge-heading">
        <h1>{t('System Image Knowledge')}</h1>
        <div className="segmented">
          <button type="button" onClick={() => context.projectId && setSourceProjectId(context.projectId)}>{t('Refresh working sources')}</button>
          <button type="button" onClick={() => context.projectId && setPlanProjectId(context.projectId)}>{t('Investigation plans')}</button>
          <button type="button" onClick={() => context.projectId && setRevisionProjectId(context.projectId)}>{t('Image revisions')}</button>
          <button type="button" onClick={() => context.projectId && setAnalysisProjectId(context.projectId)}>{t('Source analyses')}</button>
          <button className="active">{t('Graph')}</button>
          <button>{t('Objects')}</button>
          <button>{t('Search')}</button>
        </div>
      </div>
      <SourceVisibilityNotice limited={model.limited} />
      {context.systemImage.read_state && context.systemImage.read_state.mode !== 'legacy_draft' && <div className="system-image-strip" data-testid="published-image-state">
        <div><strong>{t(context.systemImage.read_state.pin ? 'Published knowledge head' : 'No published knowledge head')}</strong>
          <p>{t('This view is separate from working drafts. Publication does not approve business expectations or release quality.')}</p>
          {context.systemImage.read_state.pin && <p style={{ overflowWrap: 'anywhere' }}>
            {context.systemImage.read_state.pin.image_revision_id} · {context.systemImage.read_state.pin.image_artifact_hash}
          </p>}
        </div>
      </div>}
      {context.projectId && context.systemImage.read_state?.pin && <PublishedContextPanel
        key={`${context.projectId}:${context.systemImage.read_state.pin.publication_id}`}
        projectId={context.projectId} pin={context.systemImage.read_state.pin} />}
      {context.projectId && context.systemImage.read_state?.pin && <FrozenIndexPanel
        key={`index:${context.projectId}:${context.systemImage.read_state.pin.publication_id}`}
        projectId={context.projectId} pin={context.systemImage.read_state.pin} />}
      {context.projectId && <TestDesignReviewQueue key={`review:${context.projectId}`} projectId={context.projectId} />}
      {context.projectId && <HttpFixtureHistoryPanel key={`fixture-history:${context.projectId}`} projectId={context.projectId} />}
      {context.projectId && <ContextAuthorityRegistrationQueue key={`dependencies:${context.projectId}`} projectId={context.projectId} />}
      <div className="system-image-strip knowledge-summary">
        <div>
          <span className="eyebrow">{t('Knowledge object')}</span>
          <strong>{tx(model.selectedName)}</strong>
          <p>{tx(model.selectedDescription)}</p>
        </div>
        <div className="source-stat-grid">
          <MetricMini label={t(model.limited ? 'Visible objects' : 'Objects')} value={`${model.objectCount}`} />
          <MetricMini label={t('Relations')} unavailable={model.relationshipCount === null}
            value={model.relationshipCount === null ? t('Unavailable') : `${model.relationshipCount}`} />
          <MetricMini label={t('Chunks')} unavailable={model.chunkCount === null}
            value={model.chunkCount === null ? t('Unavailable') : `${model.chunkCount}`} />
          <MetricMini label={t('Metrics')} unavailable={model.metricCount === null}
            value={model.metricCount === null ? t('Unavailable') : `${model.metricCount}`} />
        </div>
      </div>
      <div className="quality-lane-grid knowledge-object-grid">
        {model.objects.map((object) => (
          <KnowledgeCard object={object} key={object.id}
            inspect={() => context.projectId && setInspected({ projectId: context.projectId, objectId: object.id })} />
        ))}
      </div>
      {inspectedObject && context.projectId && (
        <EvidenceInspector key={`${context.projectId}:${inspectedObject.id}`} projectId={context.projectId}
          object={inspectedObject} close={() => setInspected(null)} />
      )}
      {analysisProjectId && <AnalysisInspector key={analysisProjectId} projectId={analysisProjectId} close={() => setAnalysisProjectId(null)} />}
      {revisionProjectId && <WorkingImageInspector key={`revisions:${revisionProjectId}`} projectId={revisionProjectId}
        kind="revisions" close={() => setRevisionProjectId(null)} />}
      {planProjectId && <WorkingImageInspector key={`plans:${planProjectId}`} projectId={planProjectId}
        kind="plans" close={() => setPlanProjectId(null)} />}
      {sourceProjectId && <SourceRefreshInspector key={`sources:${sourceProjectId}`} projectId={sourceProjectId}
        close={() => setSourceProjectId(null)} />}
    </>
  )
}

function KnowledgeCard({ object, inspect }: { object: SystemImageKnowledgeCardView; inspect: () => void }) {
  const { t, tx } = useI18n()
  return (
    <div className="quality-lane-card ready" data-testid={`knowledge-card-${object.id}`}>
      <div>
        <span className="quality-lane-dot" />
        <strong>{tx(object.name)}</strong>
      </div>
      <p>{tx(object.type)} · {tx(object.branch)}</p>
      <span>{object.relationCount === null ? t('Relationships unavailable')
        : t('{confidence} confidence · {count} relations', { confidence: tx(object.confidence), count: object.relationCount })}</span>
      <button type="button" className="knowledge-evidence-button" onClick={inspect}>{t('Inspect evidence')}</button>
    </div>
  )
}
