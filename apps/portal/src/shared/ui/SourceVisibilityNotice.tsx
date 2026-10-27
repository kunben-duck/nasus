import { useI18n } from '../i18n/I18nProvider'

export function SourceVisibilityNotice({ limited }: { limited?: boolean }) {
  const { t } = useI18n()
  if (!limited) return null
  return (
    <div className="source-visibility-notice" role="status" data-testid="source-visibility-notice">
      <strong>{t('Source-filtered view')}</strong>
      <p>{t('Only authorized source-local facts are shown. Build progress, relationships and derived metrics are unavailable until their complete provenance is verified.')}</p>
    </div>
  )
}
