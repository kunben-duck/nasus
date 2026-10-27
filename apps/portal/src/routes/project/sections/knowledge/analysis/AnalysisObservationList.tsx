import type { AnalysisObservationView } from './analysisObservationView'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function AnalysisObservationList({ items }: { items: AnalysisObservationView[] }) {
  const { t, tx } = useI18n()
  return <ul className="analysis-observations" aria-label={t('Analysis observations')}>
    {items.map((item) => <li key={item.key}>
      <div className="analysis-observation-heading"><code>{item.heading}</code>
        <span className={`analysis-badge analysis-${item.status}`}>{tx(item.badge)}</span></div>
      <p>{item.language && <>{item.language} · </>}{tx(item.description)}</p>
      {item.location && <code className="analysis-location">{item.location}</code>}
      <details className="analysis-observation-details"><summary>{t('Observation details')}</summary><dl>
        {item.details.map((detail, index) => <div key={index}><dt>{tx(detail.label)}</dt>
          <dd>{detail.translateValue ? tx(detail.value) : detail.value}</dd></div>)}
      </dl></details>
    </li>)}
  </ul>
}
