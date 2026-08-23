import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { platformApi } from './api'
import type {
  ModelConfigCreateRequest,
  ModelConfigTestRequest,
  ModelConfigUpdateRequest,
  ModelRoute,
  SettingsConnectionResult,
  StudioSettings,
} from './types'
import type { BackendStatus } from '../../shared/status/backendStatus'
import { useTheme } from '../../shared/tokens/useTheme'

export type StatusDependency = {
  isLoading: boolean
  isError: boolean
}

export type StudioSettingsControls = {
  settings?: StudioSettings
  backendStatus: BackendStatus
  settingsDisabled: boolean
  statusMessage: string
  testingConnection: boolean
  connectionTestResult?: SettingsConnectionResult
  saveTheme: (theme: 'dark' | 'light' | 'system') => void
  saveLanguage: (language: 'en' | 'zh') => void
  saveNotification: (notificationMode: 'important' | 'all' | 'muted') => void
  saveModel: (payload: ModelConfigCreateRequest) => Promise<StudioSettings>
  updateModel: (configId: string, payload: ModelConfigUpdateRequest) => Promise<StudioSettings>
  testModel: (payload: ModelConfigTestRequest) => Promise<SettingsConnectionResult>
  activateModel: (configId: string) => Promise<StudioSettings>
  useSystemDefaultModel: (route: ModelRoute) => Promise<StudioSettings>
}

const settingsQueryKey = ['settings'] as const

export function useStudioSettings(statusDependencies: StatusDependency[] = []): StudioSettingsControls {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({ queryKey: settingsQueryKey, queryFn: platformApi.getSettings })
  useTheme(settingsQuery.data?.theme)

  const contentLoading = statusDependencies.some((dependency) => dependency.isLoading)
  const contentError = statusDependencies.some((dependency) => dependency.isError)
  const backendStatus: BackendStatus = settingsQuery.isLoading || contentLoading
    ? 'loading'
    : settingsQuery.isError || contentError
      ? 'offline'
      : 'live'
  const settingsDisabled = backendStatus !== 'live' || !settingsQuery.data

  const updateSettings = useMutation({
    mutationFn: (payload: Record<string, unknown>) => platformApi.updateSettings(payload),
    onSuccess: (settings) => {
      queryClient.setQueryData(settingsQueryKey, settings)
    },
  })
  const testSettingsConnection = useMutation({
    mutationFn: platformApi.testModelConfig,
  })
  const createModelConfig = useMutation({
    mutationFn: platformApi.createModelConfig,
    onSuccess: (settings) => {
      queryClient.setQueryData(settingsQueryKey, settings)
    },
  })
  const updateModelConfig = useMutation({
    mutationFn: ({ configId, payload }: { configId: string; payload: ModelConfigUpdateRequest }) =>
      platformApi.updateModelConfig(configId, payload),
    onSuccess: (settings) => {
      queryClient.setQueryData(settingsQueryKey, settings)
    },
  })
  const activateModelConfig = useMutation({
    mutationFn: platformApi.activateModelConfig,
    onSuccess: (settings) => {
      queryClient.setQueryData(settingsQueryKey, settings)
    },
  })
  const useSystemDefaultModelConfig = useMutation({
    mutationFn: platformApi.useSystemDefaultModel,
    onSuccess: (settings) => {
      queryClient.setQueryData(settingsQueryKey, settings)
    },
  })

  return {
    settings: settingsQuery.data,
    backendStatus,
    settingsDisabled,
    statusMessage: statusMessageFor(backendStatus),
    testingConnection: testSettingsConnection.isPending || createModelConfig.isPending || updateModelConfig.isPending || activateModelConfig.isPending || useSystemDefaultModelConfig.isPending,
    connectionTestResult: testSettingsConnection.data,
    saveTheme: (theme) => updateSettings.mutate({ theme }),
    saveLanguage: (language) => updateSettings.mutate({ language }),
    saveNotification: (notification_mode) => updateSettings.mutate({ notification_mode }),
    saveModel: (payload) => createModelConfig.mutateAsync(payload),
    updateModel: (configId, payload) => updateModelConfig.mutateAsync({ configId, payload }),
    testModel: (payload) => testSettingsConnection.mutateAsync(payload),
    activateModel: (configId) => activateModelConfig.mutateAsync(configId),
    useSystemDefaultModel: (route) => useSystemDefaultModelConfig.mutateAsync(route),
  }
}

function statusMessageFor(status: BackendStatus): string {
  if (status === 'loading') {
    return 'Settings are loading from the backend.'
  }
  if (status === 'offline') {
    return 'Backend is offline. Configuration is read-only preview and cannot be persisted.'
  }
  return 'Settings are connected to the backend and will be persisted securely.'
}
