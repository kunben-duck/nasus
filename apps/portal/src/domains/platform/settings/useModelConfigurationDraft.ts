import { useState } from 'react'

import type {
  CustomModelConfig,
  ModelConfigCreateRequest,
  ModelConfigTestRequest,
  ModelRoute,
  SavedModelConfig,
  StudioSettings,
} from '../types'
import { profileFor } from './modelProfiles'

export type ModelDraft = {
  displayName: string
  providerKind: CustomModelConfig['provider_kind']
  baseUrl: string
  modelName: string
  apiKey: string
}

export type ModelConfigurationValues = {
  displayName: string
  providerKind: CustomModelConfig['provider_kind']
  baseUrl: string
  modelName: string
  apiKey: string
}

export type ModelSettingsPayload = ModelConfigTestRequest & Record<string, unknown>

export const modelRoutes: ModelRoute[] = ['chat', 'embedding', 'rerank']

export function useModelConfigurationDraft(
  settings: StudioSettings | undefined,
  activeRoute: ModelRoute,
  editingConfig: SavedModelConfig | null = null,
) {
  const [drafts, setDrafts] = useState<Partial<Record<ModelRoute, Partial<ModelDraft>>>>({})
  const activeProfile = profileFor(settings, activeRoute)
  const draft = drafts[activeRoute]
  const values: ModelConfigurationValues = {
    displayName: draft?.displayName ?? editingConfig?.display_name ?? '',
    providerKind: draft?.providerKind ?? editingConfig?.provider_kind ?? activeProfile.custom_model.provider_kind,
    baseUrl: draft?.baseUrl ?? editingConfig?.base_url ?? '',
    modelName: draft?.modelName ?? editingConfig?.model_name ?? '',
    apiKey: draft?.apiKey ?? '',
  }

  function updateDraft(patch: Partial<ModelDraft>) {
    setDrafts((current) => ({
      ...current,
      [activeRoute]: {
        ...current[activeRoute],
        ...patch,
      },
    }))
  }

  return {
    activeProfile,
    values,
    payload: buildModelPayload(activeRoute, values, editingConfig?.config_id),
    updateDraft,
    resetDraft: (config?: SavedModelConfig) => setDrafts((current) => ({
      ...current,
      [activeRoute]: config
        ? {
            displayName: config.display_name,
            providerKind: config.provider_kind,
            baseUrl: config.base_url ?? '',
            modelName: config.model_name,
            apiKey: '',
          }
        : {},
    })),
  }
}

function buildModelPayload(activeRoute: ModelRoute, values: ModelConfigurationValues, configId?: string): ModelSettingsPayload {
  return {
    config_id: configId,
    model_route: activeRoute,
    display_name: values.displayName.trim() || undefined,
    custom_provider_kind: values.providerKind,
    custom_base_url: values.baseUrl,
    custom_model_name: values.modelName,
    custom_api_key: values.apiKey.trim(),
  }
}

export function buildCreateModelPayload(payload: ModelSettingsPayload, testToken: string): ModelConfigCreateRequest {
  return {
    config_id: payload.config_id,
    model_route: payload.model_route,
    display_name: typeof payload.display_name === 'string' ? payload.display_name : undefined,
    custom_provider_kind: payload.custom_provider_kind,
    custom_base_url: payload.custom_base_url,
    custom_model_name: payload.custom_model_name,
    custom_api_key: payload.custom_api_key,
    test_token: testToken,
  }
}
