import type { ModelRoute, StudioSettings } from '../../../domains/platform/types'
import { modelRouteLabel } from '../../../domains/platform/settings/modelProfiles'
import type { SettingsMenuItem } from './settingsTypes'

export function buildSettingsMenuItems(
  settings: StudioSettings | undefined,
  activeRoute: ModelRoute,
  hasProject: boolean,
): SettingsMenuItem[] {
  const items: SettingsMenuItem[] = [
    { id: 'theme', icon: '◌', label: 'Theme', value: settings?.theme ?? 'dark' },
    { id: 'language', icon: 'A', label: 'Language', value: settings?.language === 'zh' ? '中文' : 'English' },
    { id: 'model', icon: '◇', label: 'Model configuration', value: modelRouteLabel(activeRoute) },
    { id: 'notifications', icon: '◍', label: 'Applet notifications', value: settings?.notification_mode ?? 'important' },
    { id: 'account', icon: '◎', label: 'Account status', separator: true },
  ]
  if (hasProject) items.push({ id: 'members', icon: '♙', label: 'Project members' })
  items.push(
    { id: 'status', icon: '≋', label: 'View status' },
    { icon: '□', label: 'Terms of service' },
    { icon: '▱', label: 'Privacy policy' },
    { icon: '↗', label: 'Send feedback' },
    { icon: '◉', label: 'Billing Support' },
  )
  return items
}
