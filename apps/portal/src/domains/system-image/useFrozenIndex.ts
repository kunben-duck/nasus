import { useId, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { platformApi } from '../platform/api'
import { frozenIndexApi } from './frozenIndexApi'
import type { PublicationPin } from './types/frozenIndex'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }

export function useFrozenIndex(projectId: string, pin: PublicationPin) {
  const sessionId = useId(), [open, setOpen] = useState(false), [modelId, setModelId] = useState('')
  const [consent, setConsent] = useState(''), submitted = useRef(false)
  const status = useQuery({ ...sensitive, enabled: open,
    queryKey: ['frozen-index-status', projectId, pin.publication_id, sessionId],
    queryFn: ({ signal }) => frozenIndexApi.status(projectId, pin, signal) })
  const view = !status.isError && !status.isFetching ? status.data : undefined
  const models = useQuery({ ...sensitive, enabled: open && view?.can_build === true,
    queryKey: ['frozen-index-models', projectId, pin.publication_id, sessionId],
    queryFn: ({ signal }) => platformApi.getModelConfigurations('embedding', signal) })
  const choices = models.isError || models.isFetching ? [] : models.data?.configurations.filter((model) =>
    model.route === 'embedding' && !model.legacy_imported && model.last_test_result.ok === true
      && !!model.last_test_signature && !!model.last_tested_at && ['openai', 'openai_compatible'].includes(model.provider_kind)) ?? []
  // Any background revalidation invalidates the old confirmation, even when the head is unchanged.
  const scopeKey = JSON.stringify([projectId, pin, modelId, status.dataUpdatedAt, models.dataUpdatedAt])
  const preview = useMutation({ retry: false, mutationFn: async (key: string) => ({
    ...await frozenIndexApi.preview(projectId, pin, modelId), scopeKey: key,
  }) })
  const write = useMutation({ retry: false,
    mutationFn: (prepared: NonNullable<typeof preview.data>) => frozenIndexApi.build(prepared.preview, prepared.attemptKey),
    onSuccess: () => { void status.refetch() },
    onSettled: () => { setConsent(''); submitted.current = false },
  })
  const busy = preview.isPending || write.isPending
  const prepared = view?.can_build && choices.some((model) => model.config_id === modelId)
    && preview.data?.scopeKey === scopeKey && !preview.isError ? preview.data : undefined
  const confirmed = !!prepared && consent === prepared.attemptKey
  const canPreview = !busy && !!view?.can_build && choices.some((model) => model.config_id === modelId)
  const canBuild = !busy && !!prepared && confirmed && write.isIdle
  function reset() { preview.reset(); write.reset(); setConsent(''); submitted.current = false }
  return { open, status, view, models, choices, modelId, preview, prepared, write, busy, confirmed, canPreview, canBuild,
    toggle: () => { if (!busy) { setOpen(!open); reset() } },
    choose: (value: string) => { if (!busy) { setModelId(value); reset() } },
    prepare: () => { if (canPreview) { reset(); preview.mutate(scopeKey) } },
    confirm: (checked: boolean) => setConsent(checked && prepared ? prepared.attemptKey : ''),
    build: () => {
      if (!canBuild || !prepared || submitted.current) return
      submitted.current = true; setConsent(''); write.mutate(prepared)
    },
    reload: () => { if (!busy) { reset(); void status.refetch(); if (view?.can_build) void models.refetch() } },
  }
}
