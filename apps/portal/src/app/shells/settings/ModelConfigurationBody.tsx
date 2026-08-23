import { useMemo, useState } from 'react'

import type {
  ModelConfigCreateRequest,
  ModelConfigTestRequest,
  ModelConfigUpdateRequest,
  ModelRoute,
  SavedModelConfig,
  SettingsConnectionResult,
  StudioSettings,
} from '../../../domains/platform/types'
import { ModelConfigurationFields } from './ModelConfigurationFields'
import { ModelConfigurationList } from './ModelConfigurationList'
import { ModelConnectionResult } from './ModelConnectionResult'
import { buildCreateModelPayload, useModelConfigurationDraft } from '../../../domains/platform/settings/useModelConfigurationDraft'

export function ModelConfigurationBody({
  settings,
  activeRoute,
  disabled,
  testing,
  onSaveModel,
  onUpdateModel,
  onTestModel,
  onActivateModel,
  onUseSystemDefaultModel,
}: {
  settings?: StudioSettings
  activeRoute: ModelRoute
  disabled: boolean
  testing: boolean
  onSaveModel: (payload: ModelConfigCreateRequest) => Promise<StudioSettings>
  onUpdateModel: (configId: string, payload: ModelConfigUpdateRequest) => Promise<StudioSettings>
  onTestModel: (payload: ModelConfigTestRequest) => Promise<SettingsConnectionResult>
  onActivateModel: (configId: string) => Promise<StudioSettings>
  onUseSystemDefaultModel: (route: ModelRoute) => Promise<StudioSettings>
}) {
  const [mode, setMode] = useState<'list' | 'add' | 'edit'>('list')
  const [editingConfig, setEditingConfig] = useState<SavedModelConfig | null>(null)
  const [tested, setTested] = useState<{ key: string; token: string } | null>(null)
  const [testResult, setTestResult] = useState<SettingsConnectionResult | undefined>()
  const { activeProfile, values, payload, updateDraft, resetDraft } = useModelConfigurationDraft(settings, activeRoute, editingConfig)
  const testPayloadKey = useMemo(() => buildTestPayloadKey(payload), [payload])
  const displayNameOnlyUpdate = useMemo(
    () => isDisplayNameOnlyUpdate(editingConfig, values, activeRoute),
    [activeRoute, editingConfig, values],
  )

  async function testCurrentModel() {
    try {
      const result = await onTestModel(payload)
      setTestResult(result)
      setTested(result.ok && result.test_token ? { key: testPayloadKey, token: result.test_token } : null)
      return result
    } catch (error) {
      const result = failedConnectionResult(activeRoute, payload, error)
      setTestResult(result)
      setTested(null)
      return result
    }
  }

  async function saveCurrentModel() {
    if (mode === 'edit' && editingConfig) {
      if (!displayNameOnlyUpdate && !tested?.token) return
      await onUpdateModel(editingConfig.config_id, buildCreateModelPayload(payload, tested?.token ?? ''))
    } else {
      if (!tested?.token) return
      await onSaveModel(buildCreateModelPayload(payload, tested.token))
    }
    setTested(null)
    setTestResult(undefined)
    resetDraft()
    setEditingConfig(null)
    setMode('list')
  }

  if (mode === 'list') {
    return (
      <ModelConfigurationList
        route={activeRoute}
        configuration={settings?.model_configurations?.[activeRoute]}
        disabled={disabled || testing}
        onAdd={() => {
          resetDraft()
          setEditingConfig(null)
          setTested(null)
          setTestResult(undefined)
          setMode('add')
        }}
        onEdit={(config) => {
          resetDraft(config)
          setEditingConfig(config)
          setTested(null)
          setTestResult(undefined)
          setMode('edit')
        }}
        onActivateModel={(configId) => { void onActivateModel(configId) }}
        onUseSystemDefaultModel={(route) => { void onUseSystemDefaultModel(route) }}
      />
    )
  }

  return (
    <>
      <button
        className="settings-save-button secondary model-config-back"
        onClick={() => {
          setEditingConfig(null)
          setTested(null)
          setTestResult(undefined)
          setMode('list')
        }}
        type="button"
      >
        Back to models
      </button>
      <ModelConfigurationFields
        activeRoute={activeRoute}
        activeProfile={activeProfile}
        mode={mode}
        apiKeyMasked={editingConfig?.api_key_masked}
        disabled={disabled}
        testing={testing}
        values={values}
        payload={payload}
        canSave={displayNameOnlyUpdate || Boolean(tested?.token && tested.key === testPayloadKey)}
        updateDraft={(patch) => {
          if (Object.keys(patch).some((key) => key !== 'displayName')) {
            setTested(null)
            setTestResult(undefined)
          }
          updateDraft(patch)
        }}
        onSaveModel={() => { void saveCurrentModel() }}
        onTestModel={testCurrentModel}
      />
      <ModelConnectionResult activeRoute={activeRoute} testResult={testResult} />
    </>
  )
}

function buildTestPayloadKey(payload: ModelConfigTestRequest): string {
  return JSON.stringify({
    config_id: payload.config_id,
    model_route: payload.model_route,
    custom_provider_kind: payload.custom_provider_kind,
    custom_base_url: normalizeBaseUrl(payload.custom_base_url),
    custom_model_name: payload.custom_model_name.trim(),
    custom_api_key: payload.custom_api_key?.trim() ?? '',
  })
}

function isDisplayNameOnlyUpdate(
  editingConfig: SavedModelConfig | null,
  values: ReturnType<typeof useModelConfigurationDraft>['values'],
  activeRoute: ModelRoute,
): boolean {
  if (!editingConfig || editingConfig.route !== activeRoute) return false
  const nextDisplayName = values.displayName.trim() || values.modelName.trim()
  return (
    nextDisplayName !== editingConfig.display_name &&
    values.providerKind === editingConfig.provider_kind &&
    normalizeBaseUrl(values.baseUrl) === normalizeBaseUrl(editingConfig.base_url) &&
    values.modelName.trim() === editingConfig.model_name &&
    !values.apiKey.trim()
  )
}

function normalizeBaseUrl(value?: string | null): string {
  return (value ?? '').trim().replace(/\/+$/, '')
}

function failedConnectionResult(
  activeRoute: ModelRoute,
  payload: ModelConfigTestRequest,
  error: unknown,
): SettingsConnectionResult {
  return {
    ok: false,
    model_route: activeRoute,
    provider: payload.custom_provider_kind,
    model_name: payload.custom_model_name,
    runtime_mode: 'fallback',
    fallback_provider: 'mock',
    message: error instanceof Error ? error.message : 'Connection test failed.',
  }
}
