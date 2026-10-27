import type { BackendStatus } from '../../shared/status/backendStatus'
import { BackendStatusPill } from '../../shared/ui/BackendStatusPill'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function StudioTermsBar({ backendStatus }: { backendStatus: BackendStatus }) {
  const { t } = useI18n()
  return (
    <div className="terms-bar">
      <span>{t('Nasus first production baseline · system image + agent + quality loop')}</span>
      <BackendStatusPill status={backendStatus} />
      <button>{t('Learn more')}</button>
      <button>{t('Dismiss')}</button>
    </div>
  )
}
