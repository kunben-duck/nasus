import type { CodeProviderProjection } from '../../../../../domains/system-image/types/codeAnalysis'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

const enumerationLabels = { complete: 'Complete', partial: 'Partial', unknown: 'Unknown', not_run: 'Not run' }
const availabilityLabels = { observed: 'Static observation', unavailable: 'Unavailable', not_run: 'Not run' }

export function CodeProjectionDetails({ projection }: { projection?: CodeProviderProjection | null }) {
  const { t, tx } = useI18n()
  if (!projection) return <p>{t('Legacy report: provider completeness was not recorded.')}</p>
  return <details className="evidence-integrity-details" data-testid="code-projection-details">
    <summary>{t('Code graph completeness')}: {t(projection.status === 'complete' ? 'Complete' : 'Partial')}</summary>
    <p>{t('Static projection only. It does not establish business correctness or executed test coverage.')}</p>
    {projection.providers.map((provider) => <dl key={provider.capabilities.provider}>
      <dt>{t('Provider')}</dt><dd>{provider.capabilities.provider} · {provider.capabilities.provider_version}</dd>
      <dt>{t('Availability')}</dt><dd>{tx(availabilityLabels[provider.availability])}</dd>
      <dt>{t('Entity enumeration')}</dt><dd>{tx(enumerationLabels[provider.entity_enumeration])} · {provider.entity_count}</dd>
      <dt>{t('Relationship enumeration')}</dt><dd>{tx(enumerationLabels[provider.relationship_enumeration])} · {provider.relationship_count}</dd>
      <dt>{t('Source locations')}</dt><dd>{t('{exact} exact, {approximate} approximate', {
        exact: provider.exact_locations, approximate: provider.approximate_locations,
      })}</dd>
      <dt>{t('Available port operations')}</dt><dd>{provider.capabilities.operations.map((operation, index) =>
        <span key={operation}>{index > 0 ? ', ' : ''}<code>{operation}</code></span>)}</dd>
      {provider.gaps.length > 0 && <><dt>{t('Projection gaps')}</dt><dd><ul>{provider.gaps.map((gap) =>
        <li key={gap.reason}><code>{gap.reason}</code>{gap.count !== null ? ` (${gap.count})` : ''}</li>)}</ul></dd></>}
    </dl>)}
  </details>
}
