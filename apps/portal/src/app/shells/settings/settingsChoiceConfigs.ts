import type { StudioSettings } from '../../../domains/platform/types'
import type { SettingsChoice } from './settingsTypes'

export const themeChoices: SettingsChoice<StudioSettings['theme']>[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
]

export const languageChoices: SettingsChoice<StudioSettings['language']>[] = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
]

export const notificationChoices: SettingsChoice<StudioSettings['notification_mode']>[] = [
  { value: 'important', label: 'Important only' },
  { value: 'all', label: 'All notifications' },
  { value: 'muted', label: 'Muted' },
]
