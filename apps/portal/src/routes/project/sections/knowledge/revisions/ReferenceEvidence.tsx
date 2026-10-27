import { useState } from 'react'
import { useReferenceEvidence } from '../../../../../domains/system-image/useReferenceReviews'
import type { ReferenceAssertion } from '../../../../../domains/system-image/referenceReviewApi'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'

export function ReferenceEvidence({ scope, revisionId, assertion }: { scope: ImageReadScope; revisionId: string; assertion: ReferenceAssertion }) {
  const { t } = useI18n()
  const [selected, setSelected] = useState('')
  const evidence = [
    ...assertion.subject_evidence_ids.map((id) => ({ id, object: assertion.subject_object_id, label: t('Reference source') })),
    ...assertion.object_evidence_ids.map((id) => ({ id, object: assertion.object_id, label: t('Referenced requirement') })),
  ]
  const chosen = evidence.find((item) => `${item.object}:${item.id}` === selected)
  return <><label className="evidence-selector">{t('Frozen evidence reference')}<select value={selected} onChange={(e) => setSelected(e.target.value)}>
    <option value="">{t('Choose reference evidence')}</option>{evidence.map((item) => <option key={`${item.object}:${item.id}`} value={`${item.object}:${item.id}`}>{item.label} · {item.id}</option>)}
  </select></label>{chosen && <ReferenceExcerpt key={selected} scope={scope} revisionId={revisionId} objectId={chosen.object} evidenceId={chosen.id} />}</>
}

export function ReferenceExcerpt({ scope, revisionId, objectId, evidenceId }: { scope: ImageReadScope; revisionId: string; objectId: string; evidenceId: string }) {
  const { t } = useI18n()
  const [starts, setStarts] = useState<(number | undefined)[]>([undefined])
  const query = useReferenceEvidence(scope, revisionId, objectId, evidenceId, starts.at(-1))
  if (query.isError) return null
  if (query.isPending || query.isFetching) return <p role="status">{t('Verifying archived source...')}</p>
  const page = query.data
  return <><p className="image-evidence-location">{page.evidence.locator.relative_path}:{page.start_line}-{page.end_line}</p>
    <div className="evidence-source-code" role="region" aria-label={t('Archived reference evidence')} tabIndex={0}><pre>{page.content}</pre></div>
    <AnalysisPagination label={t('Evidence pages')} page={starts.length} previous={starts.length > 1 ? () => setStarts(starts.slice(0, -1)) : undefined}
      next={page.next_start_line !== null ? () => setStarts([...starts, page.next_start_line!]) : undefined} />
  </>
}
