import type {
  ModelConfigCreateRequest,
  ModelConfigTestRequest,
  ModelConfigUpdateRequest,
  ModelRoute,
  SettingsConnectionResult,
  StudioSettings,
} from '../../../domains/platform/types'
import { ModelConfigurationBody } from './ModelConfigurationBody'
import { ModelRouteTabs } from './ModelRouteTabs'
import { useModelConfigurationDraft } from '../../../domains/platform/settings/useModelConfigurationDraft'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ModelConfigurationPanel({
  settings,
  activeRoute,
  disabled,
  statusMessage,
  testing,
  onActiveRouteChange,
  onSaveModel,
  onUpdateModel,
  onTestModel,
  onActivateModel,
  onUseSystemDefaultModel,
}: {
  settings?: StudioSettings
  activeRoute: ModelRoute
  disabled: boolean
  statusMessage: string
  testing: boolean
  onActiveRouteChange: (route: ModelRoute) => void
  onSaveModel: (payload: ModelConfigCreateRequest) => Promise<StudioSettings>
  onUpdateModel: (configId: string, payload: ModelConfigUpdateRequest) => Promise<StudioSettings>
  onTestModel: (payload: ModelConfigTestRequest) => Promise<SettingsConnectionResult>
  onActivateModel: (configId: string) => Promise<StudioSettings>
  onUseSystemDefaultModel: (route: ModelRoute) => Promise<StudioSettings>
}) {
  const { t, tx } = useI18n()
  const { activeProfile } = useModelConfigurationDraft(settings, activeRoute)
  const status = activeProfile.active_provider_status

  return (
    <div className="settings-submenu settings-model-submenu">
      <div className="settings-submenu-title">{t('Model configuration')}</div>
      <div className={`settings-provider-banner compact ${disabled ? 'readonly' : ''}`}>
        <span className={`settings-provider-pill ${disabled ? 'fallback' : 'live'}`}>
          {disabled ? t('read only') : t('connected')}
        </span>
        <span className="settings-provider-copy">{statusMessage}</span>
      </div>
      <ModelRouteTabs activeRoute={activeRoute} onActiveRouteChange={onActiveRouteChange} />
      <div className="settings-provider-banner compact">
        <span className={`settings-provider-pill ${activeProfile.runtime_mode === 'live' ? 'live' : 'fallback'}`}>
          {tx(activeProfile.runtime_mode)}
        </span>
        <span className="settings-provider-copy">{tx(status.reason)}</span>
      </div>
      <ModelConfigurationBody
        key={activeRoute}
        settings={settings}
        activeRoute={activeRoute}
        disabled={disabled}
        testing={testing}
        onSaveModel={onSaveModel}
        onUpdateModel={onUpdateModel}
        onTestModel={onTestModel}
        onActivateModel={onActivateModel}
        onUseSystemDefaultModel={onUseSystemDefaultModel}
      />
    </div>
  )
}
