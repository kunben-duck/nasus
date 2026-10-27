import { useState } from 'react'
import { useImageRevisionPage, type ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { imageSectionLabels } from '../../../../../domains/system-image/imageRevisionView'
import type { ImageSection, ImageRevisionSummary } from '../../../../../domains/system-image/types/imageRevision'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { ImageRevisionRows } from './ImageRevisionRows'
import { ImageRecordNavigation } from './ImageRecordNavigation'
import { ImageRevisionProvenance } from './ImageRevisionProvenance'
import { ImageReferenceReviews } from './ImageReferenceReviews'
import { ContextPackPanel } from './ContextPackPanel'
import { ImagePublicationPanel } from './ImagePublicationPanel'
import { CodeMemberDeltaPanel } from './CodeMemberDeltaPanel'
import { NativeBuildPanel } from './NativeBuildPanel'
import type { ImageBaselineOption } from '../../../../../domains/system-image/types/baseline'

export function ImageRevisionData({ scope, revisionId, baselines, expectedPin }: {
  scope: ImageReadScope; revisionId: string; baselines: ImageBaselineOption[]; expectedPin?: ImageRevisionSummary
}) {
  const { t, tx } = useI18n()
  const [paging, setPaging] = useState<{ section: ImageSection; offsets: number[] }>({ section: 'objects', offsets: [0] })
  const selection = { section: paging.section, offset: paging.offsets.at(-1)! }
  const query = useImageRevisionPage(scope, revisionId, selection)
  const pinMismatch = expectedPin && query.data && ['project_id', 'image_revision_id', 'artifact_hash', 'baseline_id', 'manifest_id', 'manifest_hash']
    .some((key) => query.data!.revision[key as keyof ImageRevisionSummary] !== expectedPin[key as keyof ImageRevisionSummary])
  return <section className="image-revision-data">
    <div className="segmented image-revision-tabs" role="group" aria-label={t('Revision section')}>
      {(Object.keys(imageSectionLabels) as ImageSection[]).map((section) => <button key={section} type="button"
        aria-pressed={selection.section === section} className={selection.section === section ? 'active' : ''}
        onClick={() => setPaging({ section, offsets: [0] })}>{tx(imageSectionLabels[section])}</button>)}
    </div>
    {!query.isError && query.isFetching && <p role="status">{t('Verifying frozen image...')}</p>}
    {pinMismatch && <p role="alert">{t('The original build review could not be verified. No other candidate was selected and no publication was sent.')}</p>}
    {!pinMismatch && !query.isError && query.data && <div hidden={query.isFetching}>
      <div className="image-revision-status"><span>{t('Candidate · not approved')}</span>
        <p>{t('{objects} objects · {code} code entities · {relations} inferred relationships', {
          objects: query.data.revision.object_count, code: query.data.revision.code_member_count, relations: query.data.revision.relationship_count,
        })}</p></div>
      <ImageRevisionProvenance revision={query.data.revision} />
      <NativeBuildPanel scope={scope} revision={query.data.revision} />
      <CodeMemberDeltaPanel key={`delta:${revisionId}:${query.data.revision.artifact_hash}`} scope={scope} revision={query.data.revision} />
      <ImagePublicationPanel scope={scope} revision={query.data.revision} baselines={baselines} />
      <ContextPackPanel key={`${revisionId}:${query.data.revision.artifact_hash}`} scope={scope} revisionId={revisionId} imageHash={query.data.revision.artifact_hash} />
      {!query.isFetching && !query.isPlaceholderData && <>
        <p>{t('{count} frozen records', { count: query.data.total })}</p>
        <ImageRecordNavigation key={`navigation:${selection.section}:${selection.offset}`} offset={selection.offset}
          count={query.data.rows.length} total={query.data.total}
          move={(offset) => setPaging({ ...paging, offsets: [...paging.offsets, offset] })} />
        {!query.data.rows.length ? <p>{t('No records in this section. This does not establish coverage.')}</p>
          : <ImageRevisionRows key={`records:${selection.section}:${selection.offset}`} scope={scope} revisionId={revisionId} imageHash={query.data.revision.artifact_hash} rows={query.data.rows} />}
        <AnalysisPagination label={t('Revision content pages')} page={paging.offsets.length}
          previous={paging.offsets.length > 1 ? () => setPaging({ ...paging, offsets: paging.offsets.slice(0, -1) }) : undefined}
          next={query.data.nextOffset !== null ? () => setPaging({ ...paging, offsets: [...paging.offsets, query.data.nextOffset!] }) : undefined} />
      </>}
      <ImageReferenceReviews scope={scope} revisionId={revisionId} imageHash={query.data.revision.artifact_hash} />
    </div>}
  </section>
}
