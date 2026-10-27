import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { referenceReviewApi } from '../../../../../domains/system-image/referenceReviewApi'
import { useReferenceProposals } from '../../../../../domains/system-image/useReferenceReviews'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { ReferenceCandidates } from './ReferenceCandidates'

export function ImageReferenceReviews({ scope, revisionId, imageHash }: { scope: ImageReadScope; revisionId: string; imageHash: string }) {
  const { t } = useI18n()
  const client = useQueryClient()
  const [cursors, setCursors] = useState([''])
  const [chosen, setChosen] = useState('')
  const query = useReferenceProposals(scope, revisionId, cursors.at(-1)!)
  const selected = query.data?.items.find((item) => item.proposal_id === chosen)
  const mutation = useMutation({ mutationFn: () => referenceReviewApi.propose(scope.projectId, revisionId),
    onSuccess: () => client.invalidateQueries({ queryKey: ['system-image-link-reviews', scope.projectId] }) })
  return <section className="image-reference-reviews">
    <h3>{t('Reference review')}</h3>
    <p>{t('Review explicit references only. Acceptance is not test coverage, an approved oracle or image publication.')}</p>
    <button type="button" disabled={mutation.isPending} onClick={() => mutation.mutate()}>{t('Find explicit references')}</button>
    {mutation.isError && <p role="alert">{t('Reference operation failed. Check permission and reload before trying again.')}</p>}
    {query.isError ? null : query.isPending || query.isFetching || mutation.isPending ? <p role="status">{t('Checking source access...')}</p> : <>
      <label className="evidence-selector">{t('Reference proposal')}<select value={chosen} onChange={(e) => setChosen(e.target.value)}>
        <option value="">{t('Choose a reference proposal')}</option>
        {query.data.items.map((item) => <option key={item.proposal_id} value={item.proposal_id}>{item.proposal_id}</option>)}
      </select></label>
      <AnalysisPagination label={t('Reference proposal pages')} page={cursors.length}
        previous={cursors.length > 1 ? () => { setChosen(''); setCursors(cursors.slice(0, -1)) } : undefined}
        next={query.data.next_after_id ? () => { setChosen(''); setCursors([...cursors, query.data.next_after_id!]) } : undefined} />
      {selected && <ReferenceCandidates key={`${chosen}:${selected.digest}:${imageHash}`} scope={scope} revisionId={revisionId} proposalId={chosen}
        pin={{ imageArtifactHash: imageHash, proposalDigest: selected.digest }} />}
    </>}
  </section>
}
