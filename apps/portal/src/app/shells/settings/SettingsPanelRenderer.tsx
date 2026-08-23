import type { ReactNode } from 'react'
import type { ModelConfigCreateRequest, ModelConfigTestRequest, ModelConfigUpdateRequest, ModelRoute, SettingsConnectionResult, StudioSettings } from '../../../domains/platform/types'
import { AccountStatusPanel, ProviderStatusPanel } from './SettingsInfoPanels'
import { ModelConfigurationPanel } from './ModelConfigurationPanel'
import { SettingsChoicePanelRenderer } from './SettingsChoicePanelRenderer'
import { isSettingsChoicePanel } from './settingsChoicePanelIds'
import type { SettingsPanel } from './settingsTypes'

export function SettingsPanelRenderer({
  activePanel,
  activeRoute,
  settings,
  disabled,
  statusMessage,
  testing,
  accountAdministration,
  projectMembersPanel,
  onTheme,
  onLanguage,
  onNotification,
  onActiveRouteChange,
  onSaveModel,
  onUpdateModel,
  onTestModel,
  onActivateModel,
  onUseSystemDefaultModel,
}: {
  activePanel: SettingsPanel
  activeRoute: ModelRoute
  settings?: StudioSettings
  disabled: boolean
  statusMessage: string
  testing: boolean
  accountAdministration: ReactNode
  projectMembersPanel?: ReactNode
  onTheme: (theme: StudioSettings['theme']) => void
  onLanguage: (language: StudioSettings['language']) => void
  onNotification: (notificationMode: StudioSettings['notification_mode']) => void
  onActiveRouteChange: (route: ModelRoute) => void
  onSaveModel: (payload: ModelConfigCreateRequest) => Promise<StudioSettings>
  onUpdateModel: (configId: string, payload: ModelConfigUpdateRequest) => Promise<StudioSettings>
  onTestModel: (payload: ModelConfigTestRequest) => Promise<SettingsConnectionResult>
  onActivateModel: (configId: string) => Promise<StudioSettings>
  onUseSystemDefaultModel: (route: ModelRoute) => Promise<StudioSettings>
}) {
  if (isSettingsChoicePanel(activePanel)) {
    return (
      <SettingsChoicePanelRenderer
        activePanel={activePanel}
        settings={settings}
        disabled={disabled}
        onTheme={onTheme}
        onLanguage={onLanguage}
        onNotification={onNotification}
      />
    )
  }
  if (activePanel === 'account') return <AccountStatusPanel avatarEditor={accountAdministration} />

  if (activePanel === 'members') return projectMembersPanel

  if (activePanel === 'status') return <ProviderStatusPanel settings={settings} />

  return (
    <ModelConfigurationPanel
      settings={settings}
      activeRoute={activeRoute}
      disabled={disabled}
      statusMessage={statusMessage}
      testing={testing}
      onActiveRouteChange={onActiveRouteChange}
      onSaveModel={onSaveModel}
      onUpdateModel={onUpdateModel}
      onTestModel={onTestModel}
      onActivateModel={onActivateModel}
      onUseSystemDefaultModel={onUseSystemDefaultModel}
    />
  )
}
