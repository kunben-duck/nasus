import { useState } from 'react'
import type { TestDesignContext } from '../../../../../domains/system-image/types/contextPack'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { oracleKeys } from '../../../../../domains/quality-loop/acceptanceSpecificationApi'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ReferenceExcerpt } from './ReferenceEvidence'

export function ContextPackDetails({ scope, context }: { scope: ImageReadScope; context: TestDesignContext }) {
  const { t } = useI18n()
  const [chosen, setChosen] = useState<{ object: string; evidence: string } | null>(null)
  const reasons: Record<string, string> = {
    missing_requirements: t('No mandatory requirements are available.'),
    unapproved_mandatory_constraint: t('Some mandatory requirements have no approved oracle.'),
    behavior_risk_contract_not_verified: t('Behavior, risk and contract completeness is not verified.'),
    lexical_retrieval_only: t('Lexical candidates only; no semantic coverage claim.'),
    bounded_saved_trace_recall: t('Candidates replay a bounded saved search; query selection is not a relevance or coverage guarantee.'),
    structural_recall_not_run: t('Structural graph expansion has not been applied to this context.'),
    image_not_published: t('This image has not been published.'),
    model_budget_not_bound: t('Provider token budget is not bound to this draft.'),
  }
  const labels = { preconditions: t('Oracle preconditions'), action: t('Action under test'), observation: t('Observable output'), expected_result: t('Required result') }
  return <div className="context-pack-details">
    {context.publication_pin && <p data-testid="context-publication-pin">{t('Published knowledge head')}
      <code>{context.publication_pin.publication_id}</code><code>{context.publication_pin.baseline_id}</code></p>}
    <strong>{context.readiness.status === 'blocked' ? t('Blocked context') : t('Partial context')}</strong>
    <ul>{context.readiness.reason_codes.map((reason) => <li key={reason}>{reasons[reason] ?? reason}</li>)}</ul>
    <p>{t('{required} mandatory constraints · {facts} support candidates · {omitted} optional candidates omitted', {
      required: context.required_constraints.length, facts: context.facts.length, omitted: context.budget.omitted_optional_facts,
    })}</p>
    <p>{t('Budget: {used}/{max} UTF-8 bytes, not provider token usage.', { used: context.budget.used_upper_bound, max: context.budget.max_tokens })}</p>
    {context.parts && <details className="context-partitions"><summary>{t('{count} budgeted subpacks; every subpack inherits all global rules.', { count: context.parts.length })}</summary>
      <p>{t('The bundle is an index, not one model prompt. The budget applies to each subpack.')}</p>
      <ul aria-label={t('Context subpacks')}>{context.parts.map((part, index) => <li key={part.part_id}>
        <strong>{t('Subpack {number}', { number: index + 1 })}</strong>
        <p>{t('{targets} ACs · {rules} global rules · {bytes} UTF-8 bytes', { targets: part.context.partition!.target_object_ids.length,
          rules: part.context.partition!.global_constraint_ids.length, bytes: part.context.budget.used_upper_bound })}</p>
        <code>{part.part_id}</code>
        {part.context.partition!.target_object_ids.map((id) => <code key={id}>{id}</code>)}
      </li>)}</ul>
    </details>}
    <ul className="context-constraint-list" aria-label={t('Mandatory context constraints')}>
      {context.required_constraints.map((item) => <li key={item.object_id}>
        <strong>{item.oracle ? t('Approved requirement') : t('Unapproved requirement')}</strong><code>{item.object_id}</code>
        {item.source_fields.map((field, index) => <p key={index}>{field.value}</p>)}
        {item.oracle && <><code>{item.authority.revision_id}</code><dl>{oracleKeys.map((field) => <div key={field}><dt>{labels[field]}</dt><dd>{item.oracle![field]}</dd></div>)}</dl></>}
        <div className="image-link-candidate-actions">{item.evidence_ids.map((id, index) => <button key={id} className="small-btn" type="button"
          onClick={() => setChosen({ object: item.object_id, evidence: id })}>{t('Requirement evidence {number}', { number: index + 1 })}</button>)}</div>
      </li>)}
    </ul>
    <details><summary>{t('Support candidates are not verified coverage')}</summary><ul className="context-constraint-list">
      {context.facts.map((fact) => <li key={`${fact.target_object_id}:${fact.relation}:${fact.endpoint.object_id}`}>
        <strong>{fact.endpoint.title}</strong><p><code>{fact.relation}</code> · {fact.review_status}</p>
        <code>{fact.target_object_id}</code>
        <div className="image-link-candidate-actions">{fact.endpoint.evidence_ids.map((id, index) => <button key={id} type="button" className="small-btn"
          onClick={() => setChosen({ object: fact.endpoint.object_id, evidence: id })}>{t('Support evidence {number}', { number: index + 1 })}</button>)}</div>
      </li>)}
    </ul></details>
    {chosen && <ReferenceExcerpt key={`${chosen.object}:${chosen.evidence}`} scope={scope} revisionId={context.image_revision_id} objectId={chosen.object} evidenceId={chosen.evidence} />}
  </div>
}
