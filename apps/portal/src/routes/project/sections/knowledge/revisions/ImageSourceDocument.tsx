import { useState } from 'react'
import type { ImageObjectMember } from '../../../../../domains/system-image/types/imageRevision'
import { documentFieldLabels, documentGapLabels } from '../../../../../domains/system-image/sourceDocumentLabels'
import { useImageDocument, type ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { ImageLinkCandidates } from './ImageLinkCandidates'
import { AcceptanceSpecificationPanel } from './AcceptanceSpecificationPanel'

export function ImageSourceDocument({ scope, revisionId, imageHash, member }: {
  scope: ImageReadScope; revisionId: string; imageHash: string; member: ImageObjectMember
}) {
  const { t, tx } = useI18n()
  const [offsets, setOffsets] = useState([0])
  const query = useImageDocument(scope, revisionId, member, offsets.at(-1)!)
  if (query.isError) return null
  if (query.isPending || query.isFetching) return <p role="status">{t('Verifying archived source...')}</p>
  const page = query.data
  return <section className="image-source-document" aria-label={t('Source document projection')}>
    <p>{t('Source projection only. References do not prove coverage or acceptance.')}</p>
    {page.projection.external_id && <p>{page.projection.external_id}</p>}
    {page.projection.gaps.length > 0 && <p role="status">{t('Extraction gaps')}: {page.projection.gaps.map((gap) => tx(documentGapLabels[gap] ?? gap)).join(', ')}</p>}
    <dl>{page.projection.parent && <>
      <div><dt>{t('Source requirement')}</dt><dd>{page.projection.parent.external_id}</dd></div>
      <div><dt>{t('Pinned requirement revision')}</dt><dd>{page.document.parent_document_revision_id}</dd></div>
      <div><dt>{t('Specification authority')}</dt><dd>{t('Pending confirmation. Not an approved business oracle.')}</dd></div>
    </>}
    {page.fields.map((field, index) => <div key={`${field.start_line}-${index}`}>
      <dt>{tx(documentFieldLabels[field.name] ?? field.name)} · {field.start_line}-{field.end_line}</dt><dd>{field.value}</dd>
    </div>)}</dl>
    <AnalysisPagination label={t('Document field pages')} page={offsets.length}
      previous={offsets.length > 1 ? () => setOffsets(offsets.slice(0, -1)) : undefined}
      next={page.next_offset !== null ? () => setOffsets([...offsets, page.next_offset!]) : undefined} />
    {(page.document.kind === 'acceptance_criterion' || page.document.kind === 'business_rule') && <AcceptanceSpecificationPanel kind={page.document.kind}
      key={`authority:${scope.sessionId}:${revisionId}:${member.document_revision_id}`} scope={scope} revisionId={revisionId} imageHash={imageHash} bindingId={page.document.binding_id} member={member} />}
    {['acceptance_criterion', 'business_rule'].includes(page.document.kind) && <ImageLinkCandidates
      key={`candidates:${scope.sessionId}:${revisionId}:${member.document_revision_id}`} scope={scope} revisionId={revisionId} member={member} kind={page.document.kind} />}
  </section>
}
