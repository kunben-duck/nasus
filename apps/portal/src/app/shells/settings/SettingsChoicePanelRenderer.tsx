import type { StudioSettings } from '../../../domains/platform/types'
import { SettingsChoicePanel } from './SettingsChoicePanel'
import { languageChoices, notificationChoices, themeChoices } from './settingsChoiceConfigs'
import type { SettingsChoicePanelId } from './settingsChoicePanelIds'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function SettingsChoicePanelRenderer({
  activePanel,
  settings,
  disabled,
  onTheme,
  onLanguage,
  onNotification,
}: {
  activePanel: SettingsChoicePanelId
  settings?: StudioSettings
  disabled: boolean
  onTheme: (theme: StudioSettings['theme']) => void
  onLanguage: (language: StudioSettings['language']) => void
  onNotification: (notificationMode: StudioSettings['notification_mode']) => void
}) {
  const { t } = useI18n()
  if (activePanel === 'theme') {
    return <SettingsChoicePanel value={settings?.theme} disabled={disabled} choices={themeChoices(t)} onChange={onTheme} />
  }

  if (activePanel === 'language') {
    return (
      <SettingsChoicePanel value={settings?.language} disabled={disabled} choices={languageChoices(t)} onChange={onLanguage} />
    )
  }

  return (
    <SettingsChoicePanel
      value={settings?.notification_mode}
      disabled={disabled}
      choices={notificationChoices(t)}
      onChange={onNotification}
    />
  )
}
