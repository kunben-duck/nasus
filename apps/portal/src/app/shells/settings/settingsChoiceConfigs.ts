import type { StudioSettings } from '../../../domains/platform/types'
import type { SettingsChoice } from './settingsTypes'
import type { Translate } from '../../../shared/i18n/I18nProvider'

export function themeChoices(t: Translate): SettingsChoice<StudioSettings['theme']>[] {
  return [
    { value: 'light', label: t('Light') },
    { value: 'dark', label: t('Dark') },
    { value: 'system', label: t('System') },
  ]
}

export function languageChoices(t: Translate): SettingsChoice<StudioSettings['language']>[] {
  return [
    { value: 'zh', label: t('中文') },
    { value: 'en', label: t('English') },
  ]
}

export function notificationChoices(t: Translate): SettingsChoice<StudioSettings['notification_mode']>[] {
  return [
    { value: 'important', label: t('Important only') },
    { value: 'all', label: t('All notifications') },
    { value: 'muted', label: t('Muted') },
  ]
}
