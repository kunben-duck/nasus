import type { SettingsPanel } from './settingsTypes'

export type SettingsChoicePanelId = Extract<SettingsPanel, 'theme' | 'language' | 'notifications'>

export function isSettingsChoicePanel(panel: SettingsPanel): panel is SettingsChoicePanelId {
  return panel === 'theme' || panel === 'language' || panel === 'notifications'
}
