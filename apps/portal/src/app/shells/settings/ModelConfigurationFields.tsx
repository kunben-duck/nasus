import type {
  CustomModelConfig,
  ModelProviderProfile,
  ModelRoute,
  SettingsConnectionResult,
} from '../../../domains/platform/types'
import { modelPlaceholder } from '../../../domains/platform/settings/modelProfiles'
import type { ModelConfigurationValues, ModelDraft, ModelSettingsPayload } from '../../../domains/platform/settings/useModelConfigurationDraft'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ModelConfigurationFields({
  activeRoute,
  activeProfile,
  mode,
  apiKeyMasked,
  disabled,
  testing,
  values,
  payload,
  canSave,
  updateDraft,
  onSaveModel,
  onTestModel,
}: {
  activeRoute: ModelRoute
  activeProfile: ModelProviderProfile
  mode: 'add' | 'edit'
  apiKeyMasked?: string | null
  disabled: boolean
  testing: boolean
  values: ModelConfigurationValues
  payload: ModelSettingsPayload
  canSave: boolean
  updateDraft: (patch: Partial<ModelDraft>) => void
  onSaveModel: () => void
  onTestModel: (payload: ModelSettingsPayload) => Promise<SettingsConnectionResult>
}) {
  const { t } = useI18n()
  const hasUsableApiKey = Boolean(values.apiKey.trim() || (mode === 'edit' && apiKeyMasked))
  const routeLabel = activeRoute === 'chat' ? t('LLM') : activeRoute === 'embedding' ? t('Embedding') : t('Rerank')

  return (
    <div className="model-config-form">
      <label className="settings-field">
        <span className="settings-field-label">{t('Display name')}</span>
        <input className="settings-field-control" disabled={disabled} placeholder={t('{route} model', { route: routeLabel })} value={values.displayName} onChange={(event) => updateDraft({ displayName: event.target.value })} />
      </label>
      <label className="settings-field">
        <span className="settings-field-label">{t('Provider')}</span>
        <select className="settings-field-control" disabled={disabled} value={values.providerKind} onChange={(event) => updateDraft({ providerKind: event.target.value as CustomModelConfig['provider_kind'] })}>
          <option value="openai_compatible">{t('OpenAI compatible')}</option>
          <option value="openai">OpenAI</option>
          <option value="gemini">Gemini</option>
          <option value="anthropic">Anthropic</option>
        </select>
      </label>
      <label className="settings-field">
        <span className="settings-field-label">{t('Base URL')}</span>
        <input className="settings-field-control" disabled={disabled} placeholder="https://api.example.com/v1" value={values.baseUrl} onChange={(event) => updateDraft({ baseUrl: event.target.value })} />
      </label>
      <label className="settings-field">
        <span className="settings-field-label">{t('Model')}</span>
        <input className="settings-field-control" disabled={disabled} placeholder={modelPlaceholder(activeRoute)} value={values.modelName} onChange={(event) => updateDraft({ modelName: event.target.value })} />
      </label>
      <label className="settings-field">
        <span className="settings-field-label">{t('API Key')}</span>
        <input className="settings-field-control" disabled={disabled} type="password" placeholder={apiKeyMasked ? t('Keep saved key {key}', { key: apiKeyMasked }) : activeProfile.custom_model.api_key_masked ? t('Saved {key}', { key: activeProfile.custom_model.api_key_masked }) : t('Paste API key')} value={values.apiKey} onChange={(event) => updateDraft({ apiKey: event.target.value })} />
      </label>
      <div className="settings-form-actions">
        <button className="settings-save-button secondary" disabled={disabled || testing || !values.modelName.trim() || !hasUsableApiKey} onClick={() => onTestModel(payload)} type="button">
          {testing ? t('Testing...') : t('Test connection')}
        </button>
        <button className="settings-save-button" disabled={disabled || !canSave} onClick={onSaveModel} type="button">
          {mode === 'edit' ? t('Update') : t('Save')} {routeLabel}
        </button>
      </div>
    </div>
  )
}
