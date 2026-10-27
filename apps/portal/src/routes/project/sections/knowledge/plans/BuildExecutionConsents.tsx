import type { BuildExecutionConsent } from '../../../../../domains/system-image/types/buildPlan'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function BuildExecutionConsents({ items }: { items: BuildExecutionConsent[] }) {
  const { t } = useI18n()
  if (!items.length) return null
  return <section aria-label={t('Saved execution consent')}>
    <details>
      <summary>{t('Saved execution consent')}</summary>
      <p>{t('Consent applies only to the listed goal and work. Model egress and publication remain unapproved.')}</p>
      <p>{t('Saved consent is rechecked against current access, goal state and time limits before use.')}</p>
      <ul className="image-revision-rows">{items.map((item) => <li key={item.authorization_id}>
        <strong>{item.goal_id}</strong>
        <dl className="evidence-integrity-details">
          <dt>{t('Confirmed at')}</dt><dd>{item.confirmed_at}</dd>
          <dt>{t('Candidate target baseline')}</dt><dd>{item.target_baseline_id}</dd>
          <dt>{t('Pinned target version')}</dt><dd>{item.target_version_id ?? t('None')}</dd>
          <dt>{t('Approved work budget')}</dt><dd>{t('{tools} tool calls · {models} model calls · {seconds} seconds', {
            tools: item.budget.max_tool_calls, models: item.budget.max_model_calls, seconds: item.budget.max_active_seconds,
          })}</dd>
          <dt>{t('Approved work items')}</dt><dd>{item.work_item_ids.join(', ')}</dd>
          <dt>{t('Reserved work items')}</dt><dd>{item.reserved_work_item_ids.join(', ') || t('None')}</dd>
          <dt>{t('Unapproved work items')}</dt><dd>{item.unapproved_work_item_ids.join(', ') || t('None')}</dd>
        </dl>
      </li>)}</ul>
    </details>
  </section>
}
