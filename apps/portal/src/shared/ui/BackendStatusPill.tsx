import type { BackendStatus } from '../status/backendStatus'
import { useI18n } from '../i18n/I18nProvider'

export type { BackendStatus } from '../status/backendStatus'

export function BackendStatusPill({ status }: { status: BackendStatus }) {
  const { t } = useI18n()
  const label = status === 'live' ? t('Live') : status === 'loading' ? t('Connecting') : t('Offline preview')
  const copy = status === 'live'
    ? t('Backend connected')
    : status === 'loading'
      ? t('Checking backend')
      : t('Using local preview data')

  return (
    <span className={`backend-status-pill ${status}`} title={copy} data-testid="backend-status-pill">
      <span className="backend-status-dot" />
      <span>{label}</span>
    </span>
  )
}
