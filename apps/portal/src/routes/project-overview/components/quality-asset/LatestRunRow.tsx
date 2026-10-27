import type { QualityLatestRunView } from '../../projectWorkspaceSelectors'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function LatestRunRow({ latestRun }: { latestRun?: QualityLatestRunView }) {
  const { t, tx } = useI18n()
  if (!latestRun) return null

  return (
    <div className="quality-run-row">
      <span>{t('Latest run')}</span>
      <strong>{tx(latestRun.title)}</strong>
      <p>{tx(latestRun.summary)}</p>
    </div>
  )
}
