import type { ModelRoute, StudioSettings } from '../../../domains/platform/types'
import { modelRouteLabel } from '../../../domains/platform/settings/modelProfiles'
import type { Translate } from '../../../shared/i18n/I18nProvider'
import type { SettingsMenuItem } from './settingsTypes'

export function buildSettingsMenuItems(
  settings: StudioSettings | undefined,
  activeRoute: ModelRoute,
  hasProject: boolean,
  t: Translate,
): SettingsMenuItem[] {
  const route = modelRouteLabel(activeRoute)
  const routeLabel = t(route === 'embedding' ? 'Embedding' : route === 'rerank' ? 'Rerank' : 'LLM')
  const themeLabel = settings?.theme === 'light' ? t('Light') : settings?.theme === 'system' ? t('System') : t('Dark')
  const notificationLabel = settings?.notification_mode === 'all'
    ? t('All notifications')
    : settings?.notification_mode === 'muted'
      ? t('Muted')
      : t('Important only')
  const items: SettingsMenuItem[] = [
    { id: 'theme', icon: '◌', label: t('Theme'), value: themeLabel },
    { id: 'language', icon: 'A', label: t('Language'), value: settings?.language === 'zh' ? t('中文') : t('English') },
    { id: 'model', icon: '◇', label: t('Model configuration'), value: routeLabel },
    { id: 'notifications', icon: '◍', label: t('Applet notifications'), value: notificationLabel },
    { id: 'account', icon: '◎', label: t('Account status'), separator: true },
  ]
  if (hasProject) items.push({ id: 'members', icon: '♙', label: t('Project members') })
  items.push(
    { id: 'status', icon: '≋', label: t('View status') },
    { icon: '□', label: t('Terms of service') },
    { icon: '▱', label: t('Privacy policy') },
    { icon: '↗', label: t('Send feedback') },
    { icon: '◉', label: t('Billing Support') },
  )
  return items
}
