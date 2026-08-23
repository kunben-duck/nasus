export type ProviderName = 'mock' | 'openai' | 'gemini' | 'anthropic' | 'openai_compatible'
export type ModelPreset = 'system_default' | 'custom'
export type ModelRoute = 'chat' | 'embedding' | 'rerank'

export interface ProviderStatus {
  provider: ProviderName
  available: boolean
  configured_via: 'builtin' | 'system_default' | 'custom'
  mode: 'live' | 'fallback'
  fallback_provider?: 'mock' | null
  reason: string
}

export interface CustomModelConfig {
  provider_kind: 'openai_compatible' | 'openai' | 'gemini' | 'anthropic'
  base_url?: string | null
  model_name: string
  has_api_key: boolean
  api_key_masked?: string | null
}

export interface ModelProviderProfile {
  route: ModelRoute
  model_preset: ModelPreset
  model_provider: ProviderName
  model_name: string
  runtime_mode: 'live' | 'fallback'
  fallback_provider: 'mock'
  provider_statuses: ProviderStatus[]
  active_provider_status: ProviderStatus
  custom_model: CustomModelConfig
}

export type ModelRouteSelectionSource = 'system_default' | 'custom'

export interface SavedModelConfig {
  config_id: string
  route: ModelRoute
  display_name: string
  provider_kind: CustomModelConfig['provider_kind']
  base_url?: string | null
  model_name: string
  api_key_masked?: string | null
  last_tested_at: string
  last_test_signature: string
  last_test_result: Record<string, unknown>
  runtime_mode: 'live' | 'fallback'
  active: boolean
  legacy_imported: boolean
  created_at: string
  updated_at: string
}

export interface ModelRouteConfigurations {
  route: ModelRoute
  active_source: ModelRouteSelectionSource
  active_config_id?: string | null
  system_default: ModelProviderProfile
  configurations: SavedModelConfig[]
}

export interface StudioSettings {
  language: 'en' | 'zh'
  theme: 'dark' | 'light' | 'system'
  model_preset: ModelPreset
  notification_mode: 'important' | 'all' | 'muted'
  model_provider: ProviderName
  model_name: string
  runtime_mode: 'live' | 'fallback'
  fallback_provider: 'mock'
  provider_statuses: ProviderStatus[]
  active_provider_status: ProviderStatus
  custom_model: CustomModelConfig
  model_profiles: Record<ModelRoute, ModelProviderProfile>
  model_configurations: Record<ModelRoute, ModelRouteConfigurations>
}

export interface StudioSettingsConnectionTestRequest {
  model_route?: ModelRoute
  model_preset: ModelPreset
  custom_provider_kind?: CustomModelConfig['provider_kind']
  custom_base_url?: string
  custom_model_name?: string
  custom_api_key?: string
}

export interface ModelConfigTestRequest {
  config_id?: string
  model_route: ModelRoute
  display_name?: string
  custom_provider_kind: CustomModelConfig['provider_kind']
  custom_base_url?: string
  custom_model_name: string
  custom_api_key?: string
}

export interface ModelConfigCreateRequest extends ModelConfigTestRequest {
  test_token: string
}

export type ModelConfigUpdateRequest = ModelConfigCreateRequest

export interface SettingsConnectionResult {
  ok: boolean
  model_route?: ModelRoute
  provider: ProviderName
  model_name: string
  runtime_mode: 'live' | 'fallback'
  fallback_provider?: 'mock' | null
  latency_ms?: number | null
  message: string
  test_token?: string | null
  fingerprint?: string | null
}
