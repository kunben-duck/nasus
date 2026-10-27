import { useBuildPlan } from '../../../../../domains/system-image/useBuildPlans'
import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { BaselineRecord } from '../../../../../domains/system-image/types/baseline'
import { StructureBuildAction } from './StructureBuildAction'
import { BuildExecutionConsents } from './BuildExecutionConsents'
import { BuildPlanRevisionAction } from './BuildPlanRevisionAction'
import { SavedBuildAgentAction } from './SavedBuildAgentAction'

export function BuildPlanDetails({ scope, planId, baselines, manifestId }: { scope: ImageReadScope; planId: string; baselines: BaselineRecord[]; manifestId?: string }) {
  const { t } = useI18n()
  const query = useBuildPlan(scope, planId)
  if (query.isError) return null
  if (query.isPending) return <p role="status">{t('Checking source access...')}</p>
  const { proposal, plan_digest } = query.data
  return <>
    {query.isFetching && <p role="status">{t('Checking source access...')}</p>}
    <section hidden={query.isFetching} aria-label={t('Investigation draft')} className="build-plan-details">
    <h3>{proposal.intent.objective}</h3><p>{t('Saved proposal. Confirmed work and resulting candidates are recorded separately.')}</p>
    <SavedBuildAgentAction key={JSON.stringify([scope.sessionId, scope.projectId, planId, plan_digest])} scope={scope} plan={query.data} />
    <StructureBuildAction scope={scope} plan={query.data} baselines={baselines} />
    <BuildExecutionConsents items={query.data.execution_authorizations ?? []} />
    <BuildPlanRevisionAction scope={scope} plan={query.data} manifestId={manifestId} />
    <dl className="evidence-integrity-details"><dt>{t('Source manifest')}</dt><dd>{proposal.intent.source_manifest_id}</dd>
      {proposal.intent.target && <><dt>{t('Build intent target')}</dt><dd>{proposal.intent.target.target_baseline_id}</dd>
        <dt>{t('Pinned target version')}</dt><dd>{proposal.intent.target.target_version_id ?? t('None')}</dd>
        <dt>{t('Expected publication head')}</dt><dd>{proposal.intent.target.expected_head_id ?? t('None')}</dd></>}
      <dt>{t('Plan digest')}</dt><dd>{plan_digest}</dd><dt>{t('Proposed budget')}</dt>
      <dd>{t('{tools} tool calls · {models} model calls · {seconds} seconds', { tools: proposal.intent.budget.max_tool_calls,
        models: proposal.intent.budget.max_model_calls, seconds: proposal.intent.budget.max_active_seconds })}</dd>
      <dt>{t('Proposed cost ceiling (USD, optional)')}</dt>
      <dd>{proposal.intent.budget.max_cost_microusd === null ? t('Not specified') : `$${proposal.intent.budget.max_cost_microusd / 1_000_000}`}</dd></dl>
    <h3>{t('Investigation tasks')}</h3>
    <ol className="image-revision-rows">{proposal.work_items.map((item) => <li key={item.work_item_id}>
      <strong>{item.question}</strong><p>{item.reason}</p><p>{item.binding_state} · {item.proposed_tool_id ?? item.capability}</p>
      <p>{t('Depends on')}: {item.dependency_ids.join(', ') || t('None')}</p>
      <ul>{item.acceptance_conditions.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul>
    </li>)}</ol>
    <h3>{t('Unresolved gaps')}</h3><ul className="image-revision-rows">{proposal.gaps.map((gap) => <li key={gap.code}>
      <strong>{gap.code} · {gap.blocks}</strong><p>{gap.reason}</p><p>{gap.required_action}</p>
    </li>)}</ul>
    <details className="evidence-integrity-details"><summary>{t('Pinned source revisions')}</summary>
      <ul>{proposal.intent.sources.map((source) => <li key={source.binding_id}>{source.source_type} · {source.status}
        <p>{source.binding_id}</p><p>{source.source_revision_id ?? t('Unavailable')}</p></li>)}</ul></details>
    </section>
  </>
}
