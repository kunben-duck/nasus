import { useState } from 'react'
import type { ReactNode } from 'react'

import type { ModelConfigCreateRequest, ModelConfigTestRequest, ModelConfigUpdateRequest, ModelRoute, SettingsConnectionResult, StudioSettings } from '../../../domains/platform/types'
import { SettingsMenu } from './SettingsMenu'
import { SettingsPanelRenderer } from './SettingsPanelRenderer'
import { buildSettingsMenuItems } from './settingsMenuModel'
import type { SettingsPanel } from './settingsTypes'

export function SettingsPopover({
  settings,
  disabled,
  statusMessage,
  testing,
  accountAdministration,
  projectMembersPanel,
  onTheme,
  onLanguage,
  onNotification,
  onSaveModel,
  onUpdateModel,
  onTestModel,
  onActivateModel,
  onUseSystemDefaultModel,
}: {
  settings?: StudioSettings
  disabled: boolean
  statusMessage: string
  testing: boolean
  accountAdministration: ReactNode
  projectMembersPanel?: ReactNode
  onTheme: (theme: 'dark' | 'light' | 'system') => void
  onLanguage: (language: 'en' | 'zh') => void
  onNotification: (notificationMode: 'important' | 'all' | 'muted') => void
  onSaveModel: (payload: ModelConfigCreateRequest) => Promise<StudioSettings>
  onUpdateModel: (configId: string, payload: ModelConfigUpdateRequest) => Promise<StudioSettings>
  onTestModel: (payload: ModelConfigTestRequest) => Promise<SettingsConnectionResult>
  onActivateModel: (configId: string) => Promise<StudioSettings>
  onUseSystemDefaultModel: (route: ModelRoute) => Promise<StudioSettings>
}) {
  const [activePanel, setActivePanel] = useState<SettingsPanel>('theme')
  const [activeRoute, setActiveRoute] = useState<ModelRoute>('chat')
  const menuItems = buildSettingsMenuItems(settings, activeRoute, Boolean(projectMembersPanel))

  return (
    <div className="settings-pop">
      <SettingsMenu items={menuItems} activePanel={activePanel} onSelect={setActivePanel} />
      <SettingsPanelRenderer
        activePanel={activePanel}
        activeRoute={activeRoute}
        settings={settings}
        disabled={disabled}
        statusMessage={statusMessage}
        testing={testing}
        accountAdministration={accountAdministration}
        projectMembersPanel={projectMembersPanel}
        onTheme={onTheme}
        onLanguage={onLanguage}
        onNotification={onNotification}
        onActiveRouteChange={setActiveRoute}
        onSaveModel={onSaveModel}
        onUpdateModel={onUpdateModel}
        onTestModel={onTestModel}
        onActivateModel={onActivateModel}
        onUseSystemDefaultModel={onUseSystemDefaultModel}
      />
    </div>
  )
}
