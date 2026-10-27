import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { requireRunPlan } from './runPlanValidation'
import { environmentRequest } from './environmentRecordValidation'
import type { createOriginalObservationApi } from './originalObservationApi'
import type { createEnvironmentRecovery } from './environmentRecordRecovery'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildArchive } from './types/runPlanBuilds'
import type { EnvironmentRecordAttempt } from './types/environmentRecords'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useOriginalObservation<T extends { metadata: unknown }>(plan: RunPlanArchive, binding: RunPlanBuildArchive,
  actorId: string, current: boolean, onFailure: () => void, definition: {
    key: string; api: ReturnType<typeof createOriginalObservationApi<T>>; storage: ReturnType<typeof createEnvironmentRecovery>
  }) {
  const client = useQueryClient(), input = environmentRequest(plan, binding), { api, storage } = definition
  const readStored = () => {
    try { return { attempt: storage.read(actorId, input.project_id, input.run_plan_id, input.run_plan_artifact_hash,
      input.build_binding_id, input.build_binding_artifact_hash), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  }
  const [open, setOpen] = useState(false), [consent, setConsent] = useState(''), [stored, setStored] = useState(readStored)
  const submitted = useRef(false), prefix = [definition.key, actorId, ...Object.values(input)]
  const declaration = plan.artifact.plan.selection.environment
  const canRegister = current && plan.current_use.inputs_current && binding.current_use.inputs_current
    && declaration.kind === 'local' && declaration.base_url === 'http://127.0.0.1:8080'
  const write = useMutation({ retry: false, mutationFn: async (attempt?: EnvironmentRecordAttempt) => {
    if (attempt) return api.confirm(attempt)
    const value = { projectId: input.project_id, planId: input.run_plan_id, planHash: input.run_plan_artifact_hash,
      bindingId: input.build_binding_id, bindingHash: input.build_binding_artifact_hash,
      requestKey: crypto.randomUUID(), requestHash: await canonicalDigest(input) }
    storage.save(actorId, value); setStored({ attempt: value, invalid: false })
    return api.register(input, value, (ack) => {
      storage.acknowledge(actorId, ack); setStored({ attempt: ack, invalid: false })
    })
  }, onSettled: () => { setConsent(''); void client.invalidateQueries({ queryKey: [...prefix, 'original'] }) } })
  const recovery = useQuery({ ...sensitive, enabled: open && !!stored.attempt && !write.isPending,
    queryKey: [...prefix, 'original', stored.attempt?.requestKey, plan.current_use, binding.current_use], queryFn: async ({ signal }) => {
      requireRunPlan(stored.attempt)
      const value = await api.recover(stored.attempt, plan, binding, signal)
      const attempt = { ...stored.attempt, commandId: value.command.id }
      signal.throwIfAborted(); storage.acknowledge(actorId, attempt)
      return { ...value, attempt }
    }, refetchInterval: (q) => ['pending', 'running'].includes(q.state.data?.command.status ?? '') ? 10000 : false })
  const original = !write.isPending && !recovery.isFetching && !recovery.isError ? recovery.data : undefined
  const archive = useQuery({ ...sensitive, enabled: open && original?.command.status === 'completed',
    queryKey: [...prefix, 'archive', original?.command.id, plan.current_use, binding.current_use], queryFn: ({ signal }) => {
      requireRunPlan(original); return api.read(original.command, plan, binding, signal)
    } })
  const denied = recovery.error instanceof ApiRequestError && [403, 502].includes(recovery.error.status)
  const failed = open && (archive.isError || denied)
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const busy = write.isPending || recovery.isFetching || archive.isFetching
  const confirmationKey = JSON.stringify([definition.key, input, plan.current_use, binding.current_use, canRegister, original?.command.id,
    original?.command.status, recovery.dataUpdatedAt])
  const confirmed = consent === confirmationKey
  const maySave = open && canRegister && !busy && !failed && !stored.invalid && !stored.attempt && !write.isError && confirmed
  const mayConfirm = open && canRegister && !busy && !failed && original?.command.status === 'waiting_confirmation' && confirmed
  const result = original && !archive.isFetching && !archive.isError ? archive.data : undefined
  return { open, input, stored, original, result, busy, failed, recovery, write, canRegister, confirmed, maySave, mayConfirm,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    confirm: (checked: boolean) => setConsent(checked ? confirmationKey : ''),
    save: () => { if (maySave && !submitted.current) { submitted.current = true; setConsent(''); write.mutate(undefined) } },
    confirmOriginal: () => { if (mayConfirm && original && !submitted.current) { submitted.current = true; setConsent(''); write.mutate(original.attempt) } },
    reload: () => { if (!busy) { setConsent(''); submitted.current = false; setStored(readStored())
      if (stored.attempt) void recovery.refetch(); if (original?.command.status === 'completed') void archive.refetch()
    } },
    another: () => { if (!busy && result && original) { storage.clear(actorId, original.attempt)
      setStored({ attempt: null, invalid: false }); submitted.current = false; setConsent(''); write.reset()
    } },
  }
}
