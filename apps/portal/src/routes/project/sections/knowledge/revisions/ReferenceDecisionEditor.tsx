import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { referenceReviewApi, type ReferenceAssertion, type ReviewChoice, type ReviewPage } from '../../../../../domains/system-image/referenceReviewApi'
import { useReferenceHistory } from '../../../../../domains/system-image/useReferenceReviews'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { ReferenceEvidence } from './ReferenceEvidence'
import { FreezeReferenceReview } from './FreezeReferenceReview'

export function ReferenceDecisionEditor({ scope, revisionId, proposalId, assertion, parentArtifactHash, proposalDigest }: {
  scope: ImageReadScope; revisionId: string; proposalId: string; assertion: ReferenceAssertion; parentArtifactHash: string; proposalDigest: string
}) {
  const { t } = useI18n()
  const [offsets, setOffsets] = useState([0])
  const query = useReferenceHistory(scope, revisionId, proposalId, assertion.assertion_id, offsets.at(-1)!, proposalDigest)
  if (query.isError) return null
  if (query.isPending || query.isFetching) return <p role="status">{t('Checking source access...')}</p>
  return <section className="reference-decision-editor">
    <h4>{assertion.reference_id}</h4>
    <ReferenceEvidence scope={scope} revisionId={revisionId} assertion={assertion} />
    <p>{t('Review history: {count} decisions', { count: query.data.total })}</p>
    {query.data.items.map((item) => <article key={item.decision_id} className="reference-decision-row">
      <strong>{item.decision === 'accept' ? t('Accepted reference') : item.decision === 'reject' ? t('Rejected reference') : t('Deferred reference')}</strong>
      <p>{item.reason}</p><small>{item.reviewer_actor} · {item.recorded_at}</small>
    </article>)}
    <AnalysisPagination label={t('Review history pages')} page={offsets.length}
      previous={offsets.length > 1 ? () => setOffsets(offsets.slice(0, -1)) : undefined}
      next={query.data.next_offset !== null ? () => setOffsets([...offsets, query.data.next_offset!]) : undefined} />
    <ReviewForm key={query.data.head_decision_id ?? 'unreviewed'} page={query.data} />
    {query.data.items.some((item) => item.decision_id === query.data.head_decision_id) &&
      <FreezeReferenceReview key={`freeze:${query.data.head_decision_id}`} page={query.data} parentArtifactHash={parentArtifactHash} />}
  </section>
}

function ReviewForm({ page }: { page: ReviewPage }) {
  const { t } = useI18n()
  const client = useQueryClient()
  const [decision, setDecision] = useState<ReviewChoice>('defer')
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const mutation = useMutation({ mutationFn: () => referenceReviewApi.review(page, decision, reason),
    onSuccess: () => client.invalidateQueries({ predicate: (query) => query.queryKey[0] === 'system-image-link-reviews'
      && query.queryKey[1] === page.project_id && query.queryKey[3] === 'decisions' }) })
  return <form onSubmit={(e) => { e.preventDefault(); if (confirmed && reason.trim()) mutation.mutate() }}>
    <label>{t('Review decision')}<select value={decision} disabled={mutation.isPending} onChange={(e) => { setDecision(e.target.value as ReviewChoice); setConfirmed(false) }}>
      <option value="accept">{t('Accept reference')}</option><option value="reject">{t('Reject reference')}</option><option value="defer">{t('Defer reference')}</option>
    </select></label>
    <label>{t('Review reason')}<textarea required maxLength={2000} value={reason} disabled={mutation.isPending} onChange={(e) => { setReason(e.target.value); setConfirmed(false) }} /></label>
    <label className="reference-review-confirm"><input type="checkbox" checked={confirmed} disabled={mutation.isPending} onChange={(e) => setConfirmed(e.target.checked)} />
      {t('Confirm this decision for these exact revisions. This does not approve coverage or publication.')}</label>
    <button type="submit" disabled={!confirmed || !reason.trim() || mutation.isPending || mutation.isError}>{t('Record review')}</button>
    {mutation.isError && <p role="alert">{t('Reference operation failed. Check permission and reload before trying again.')}</p>}
  </form>
}
