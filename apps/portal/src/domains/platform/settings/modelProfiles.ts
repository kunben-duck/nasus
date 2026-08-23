import type {
  ModelProviderProfile,
  ModelRoute,
  StudioSettings,
} from '../types'

export function modelRouteLabel(route: ModelRoute): string {
  return route === 'chat' ? 'LLM' : route
}

export function modelPlaceholder(route: ModelRoute): string {
  if (route === 'embedding') return 'text-embedding-3-large'
  if (route === 'rerank') return 'rerank-model'
  return 'gpt-5.4'
}

export function profileFor(settings: StudioSettings | undefined, route: ModelRoute): ModelProviderProfile {
  const fallback: ModelProviderProfile = {
    route,
    model_preset: 'system_default',
    model_provider: 'openai',
    model_name: modelPlaceholder(route),
    runtime_mode: 'fallback',
    fallback_provider: 'mock',
    provider_statuses: [],
    active_provider_status: {
      provider: 'openai',
      available: false,
      configured_via: 'system_default',
      mode: 'fallback',
      fallback_provider: 'mock',
      reason: 'Settings are loading.',
    },
    custom_model: {
      provider_kind: 'openai_compatible',
      base_url: null,
      model_name: '',
      has_api_key: false,
      api_key_masked: null,
    },
  }
  return settings?.model_profiles?.[route] ?? fallback
}
