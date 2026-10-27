import { useState } from 'react'
import { useLinkCandidates } from '../../../../../domains/system-image/useLinkCandidates'
import type { LinkCandidateEndpoint, LinkCandidatePage } from '../../../../../domains/system-image/linkCandidateApi'
import { useSemanticEvaluation } from '../../../../../domains/system-image/useSemanticEvaluation'
import type { ImageObjectMember } from '../../../../../domains/system-image/types/imageRevision'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ReferenceExcerpt } from './ReferenceEvidence'
import { SemanticEvaluationPanel } from './semantic/SemanticEvaluationPanel'

export function ImageLinkCandidates({ scope, revisionId, member, kind }: {
  scope: ImageReadScope; revisionId: string; member: ImageObjectMember; kind: string
}) {
  const { t } = useI18n()
  const { mutation, query } = useLinkCandidates(scope, revisionId, member)
  const pending = mutation.isPending || (mutation.isSuccess && (query.isPending || query.isFetching))
  const page = !pending && !query.isError && !mutation.isError ? query.data : undefined
  return <section className="image-link-candidates" aria-label={t('Related code and test candidates')}>
    <div className="image-link-candidate-actions">
      <button className="small-btn" disabled={pending} onClick={() => mutation.mutate({ relation: 'implements' })}>{t('Find related code')}</button>
      {kind === 'acceptance_criterion' && <button className="small-btn" disabled={pending} onClick={() => mutation.mutate({ relation: 'asserts' })}>{t('Find related tests')}</button>}
    </div>
    <p>{t('Recall candidates only. Matching names or references do not prove implementation or test coverage.')}</p>
    {pending && <p role="status">{t('Verifying candidate evidence...')}</p>}
    {(query.isError || mutation.isError) && <p role="alert">{t('Candidate evidence could not be verified. Reload the image.')}</p>}
    {page && <>
      <p>{t('Retrieved candidates')}: {page.items.length} / {page.matched_count} · {t('Eligible endpoints')}: {page.eligible_count}</p>
      <p>{t('Lexical and explicit-reference recall. Vector and structural recall have not run.')}</p>
      <p>{t('Review status is fixed at query time. Find candidates again to refresh; model evaluation checks current reviews.')}</p>
      {!!page.excluded.historical_review && <p role="status">{t('Excluded by historical review before limiting')}: {page.excluded.historical_review}</p>}
      {!!page.excluded.missing_expected_result && <p role="status">{t('Excluded tests without expected results')}: {page.excluded.missing_expected_result}</p>}
      {!!page.excluded.missing_code_evidence && <p role="status">{t('Excluded code without source evidence')}: {page.excluded.missing_code_evidence}</p>}
      {page.items.length === 0 && <p>{t('No matching candidates. This does not prove there is no related implementation or test.')}</p>}
      {page.truncated && <p role="status">{t('More matches exist than the selected recall limit.')}
        {mutation.data!.limit < 100 && <button className="small-btn" onClick={() => mutation.mutate({ relation: page.relation, limit: 100 })}>{t('Expand recall to 100')}</button>}
      </p>}
      <CandidateResults key={mutation.data!.invocationId} scope={scope} page={page} recallLimit={mutation.data!.limit} recallInvocationId={mutation.data!.invocationId} />
    </>}
  </section>
}

function CandidateResults({ scope, page, recallLimit, recallInvocationId }: { scope: ImageReadScope; page: LinkCandidatePage; recallLimit: number; recallInvocationId: string }) {
  const { t } = useI18n()
  const state = useSemanticEvaluation(scope, page, recallLimit, recallInvocationId)
  return <>
    <ul className="link-candidate-list" aria-label={t('Retrieved candidates')}>
      {page.items.map((item) => <li key={item.endpoint.revision_id}>
        <label className="semantic-candidate-choice"><input type="checkbox" checked={state.subjects.includes(item.endpoint.object_id)}
          disabled={state.busy || (state.subjects.length >= 30 && !state.subjects.includes(item.endpoint.object_id))}
          onChange={() => state.toggle(item.endpoint.object_id)} aria-label={t('Select candidate: {name}', { name: item.endpoint.title })} />
          <strong>{item.endpoint.title}</strong></label><span>{t('Not asserted')}</span>
        {item.review_status === 'requires_revalidation' && <p>{t('Source changed: revalidation required')}</p>}
        {item.review_status === 'reviewed_not_approved' && <p>{t('Previously reviewed; approval is not transferred')}</p>}
        <p>{t('Pinned revision')}: <code>{item.endpoint.revision_id}</code></p>
        <LinkCandidateEvidence scope={scope} revisionId={page.image_revision_id} target={page.target} candidate={item.endpoint} />
      </li>)}
    </ul>
    <SemanticEvaluationPanel scope={scope} page={page} state={state} />
  </>
}

function LinkCandidateEvidence({ scope, revisionId, target, candidate }: {
  scope: ImageReadScope; revisionId: string; target: LinkCandidateEndpoint; candidate: LinkCandidateEndpoint
}) {
  const { t } = useI18n()
  const [selected, setSelected] = useState('')
  const options = [target, candidate].flatMap((endpoint, index) => endpoint.evidence_ids.map((id) => ({
    value: `${endpoint.object_id}:${id}`, id, object: endpoint.object_id,
    label: `${index === 0 ? t('Target specification evidence') : t('Candidate source evidence')} · ${id}`,
  })))
  const option = options.find((item) => item.value === selected)
  return <><label className="evidence-selector">{t('Candidate evidence')}<select value={selected} onChange={(event) => setSelected(event.target.value)}>
    <option value="">{t('Choose reference evidence')}</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
  </select></label>
    {option && <ReferenceExcerpt key={selected} scope={scope} revisionId={revisionId} objectId={option.object} evidenceId={option.id} />}
  </>
}
