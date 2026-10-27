import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function AnalysisPagination({ previous, next, page, label }: { previous?: () => void; next?: () => void; page: number; label?: string }) {
  const { t } = useI18n()
  if (!previous && !next) return null
  return <div className="analysis-pagination" role={label ? 'group' : undefined} aria-label={label}>
    <button type="button" onClick={previous} disabled={!previous}>{t('Previous page')}</button>
    <span>{t('Page {page}', { page })}</span>
    <button type="button" onClick={next} disabled={!next}>{t('Next page')}</button>
  </div>
}
