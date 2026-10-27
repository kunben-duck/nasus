import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import type { ImageObjectMember } from '../../../../../domains/system-image/types/imageRevision'
import { useAcceptanceSpecification } from '../../../../../domains/quality-loop/useAcceptanceSpecification'
import { oracleKeys, type AuthorityKind } from '../../../../../domains/quality-loop/acceptanceSpecificationApi'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import './semantic/semantic-evaluation.css'

export function AcceptanceSpecificationPanel({ scope, revisionId, imageHash, bindingId, member, kind = 'acceptance_criterion' }: {
  scope: ImageReadScope; revisionId: string; imageHash: string; bindingId: string; member: ImageObjectMember; kind?: AuthorityKind
}) {
  const { t } = useI18n()
  const state = useAcceptanceSpecification({ project_id: scope.projectId, image_revision_id: revisionId, image_artifact_hash: imageHash,
    object_id: member.object_id, binding_id: bindingId, source_revision_id: member.source_revision_id!, document_revision_id: member.document_revision_id! },
    member.evidence_ids, scope.sessionId, scope.onFailure, kind)
  const rule = kind === 'business_rule'
  const labels = { preconditions: t('Oracle preconditions'), action: t('Action under test'), observation: t('Observable output'), expected_result: t('Required result') }
  const view = state.view
  return <section className="semantic-review" aria-label={rule ? t('Business rule authority') : t('Requirement authority')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.write.isPending} onClick={state.toggle}>{rule ? t('Inspect business rule authority') : t('Inspect requirement authority')}</button>
    {state.open && <>
      <p>{rule ? t('Confirm the business rule independently of code or model output. The complete rule is retained in every context part for this exact image; this does not prove coverage or publish the image.') : t('Approve the requirement independently of implementation or model agreement. Applies only to this exact image; does not publish it or prove coverage.')}</p>
      <button className="small-btn" disabled={state.query.isFetching || state.write.isPending} onClick={state.reload}>{t('Reload authority')}</button>
      {state.query.isFetching && <p role="status">{t('Checking source access...')}</p>}
      {state.write.isPending && <p role="status">{rule ? t('Recording business rule authority...') : t('Recording requirement authority...')}</p>}
      {state.write.isSuccess && <p role="status">{rule ? t('Business rule authority recorded. Other images do not inherit it.') : t('Requirement authority recorded. Other images do not inherit it.')}</p>}
      {state.write.isError && <p role="alert">{state.stale ? t('Authority changed. Reload and confirm a new decision.') : t('Authority was not acknowledged. Reload before retrying; no automatic retry was sent.')}</p>}
      {view && <>
        <div className="semantic-review-head"><strong>{rule
          ? (view.head ? (view.head.status === 'approved' ? t('Approved business rule') : t('Withdrawn business rule')) : t('Unapproved business rule'))
          : (view.head ? (view.head.status === 'approved' ? t('Approved requirement') : t('Withdrawn requirement')) : t('Unapproved requirement'))}</strong>
          {view.head && <><p><code>{view.head.revision_id}</code></p><small>{view.head.authority_actor} · <time>{view.head.recorded_at}</time></small></>}
          {view.current?.oracle && <dl>{oracleKeys.map((field) => <div key={field}><dt>{labels[field]}</dt><dd>{view.current!.oracle![field]}</dd></div>)}</dl>}
        </div>
        {view.can_review ? <fieldset disabled={state.write.isPending || !state.write.isIdle}>
          <legend>{rule ? t('Business rule authority decision') : t('Requirement authority decision')}</legend>
          <label>{t('Review decision')}<select value={state.decision} onChange={(event) => state.choose(event.target.value as 'approve' | 'withdraw')}>
            <option value="approve">{rule ? t('Approve business rule') : t('Approve requirement')}</option><option value="withdraw" disabled={view.head?.status !== 'approved'}>{rule ? t('Withdraw business rule') : t('Withdraw requirement')}</option>
          </select></label>
          {state.decision === 'approve' && oracleKeys.map((field) => <label key={field}>{labels[field]}
            <textarea rows={2} maxLength={2000} value={state.oracle[field]} onChange={(event) => state.edit(field, event.target.value)} /></label>)}
          <label>{t('Review reason')}<textarea rows={2} maxLength={2000} value={state.reason} onChange={(event) => state.explain(event.target.value)} /></label>
          <label className="semantic-confirm"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
            {rule ? (state.decision === 'approve' ? t('I independently confirm this business rule and observable oracle, not behavior inferred from code or generated tests.') : t('I confirm withdrawal of this exact business rule authority revision.'))
              : (state.decision === 'approve' ? t('I independently confirm this requirement and observable oracle, not merely behavior inferred from code or generated tests.') : t('I confirm withdrawal of this exact requirement authority revision.'))}</label>
          <button className="small-btn primary" disabled={!state.canSubmit} onClick={state.submit}>{t('Record authority decision')}</button>
        </fieldset> : <p>{t('Only a project reviewer can approve requirement authority.')}</p>}
      </>}
    </>}
  </section>
}
