import type { StudioSettings } from '../../../domains/platform/types'
import { SettingsChoicePanel } from './SettingsChoicePanel'
import { languageChoices, notificationChoices, themeChoices } from './settingsChoiceConfigs'
import type { SettingsChoicePanelId } from './settingsChoicePanelIds'

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
  if (activePanel === 'theme') {
    return <SettingsChoicePanel value={settings?.theme} disabled={disabled} choices={themeChoices} onChange={onTheme} />
  }

  if (activePanel === 'language') {
    return (
      <SettingsChoicePanel value={settings?.language} disabled={disabled} choices={languageChoices} onChange={onLanguage} />
    )
  }

  return (
    <SettingsChoicePanel
      value={settings?.notification_mode}
      disabled={disabled}
      choices={notificationChoices}
      onChange={onNotification}
    />
  )
}
