import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import { readOriginalBuilds, runPlanBuildApi } from './runPlanBuildApi'
import { buildRecovery } from './runPlanBuildRecovery'
import { buildSelection, expectedBuildBinding, originalCodeSources } from './runPlanBuildValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { RunPlanBuildAttempt, RunPlanBuildRequest } from './types/runPlanBuilds'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useRunPlanBuild(plan: RunPlanArchive, actorId: string, current: boolean, onFailure: () => void) {
  const client = useQueryClient(), m = plan.metadata, code = originalCodeSources(plan)
  const [open, setOpen] = useState(false), [ids, setIds] = useState(() => Object.fromEntries(code.map((s) => [s.binding_id, ''])))
  const [target, setTarget] = useState(''), [reason, setReason] = useState(''), [consent, setConsent] = useState('')
  const [stored, setStored] = useState(() => {
    try { return { attempt: buildRecovery.read(actorId, m.project_id, m.run_plan_id, m.artifact_hash), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  })
  const submitted = useRef(false), prefix = ['run-plan-builds', m.project_id, actorId, m.run_plan_id, m.artifact_hash]
  const canBind = current && plan.current_use.inputs_current, key = JSON.stringify([ids, target, reason, plan.current_use, canBind])
  const verify = useMutation({ retry: false, mutationFn: async () => {
    const values = await readOriginalBuilds(plan, code.map((s) => ids[s.binding_id].trim()), new AbortController().signal)
    requireRunPlan(values.every((v, i) => v.receipt.source.pin.binding_id === code[i].binding_id && v.receipt.source.pin.source_revision_id === code[i].source_revision_id))
    const selection = buildSelection(plan, values, target, reason)
    await expectedBuildBinding(plan, selection, values)
    return { key, builds: values, selection, value: await runPlanBuildApi.preview(selection, plan, values) }
  } })
  const prepared = canBind && !verify.isPending && !verify.isError && verify.data?.key === key ? verify.data : undefined
  const write = useMutation({ retry: false, mutationFn: async (value: { input: RunPlanBuildRequest } | { attempt: RunPlanBuildAttempt }) => {
    if ('attempt' in value) return runPlanBuildApi.confirm(value.attempt)
    const attempt = { projectId: m.project_id, planId: m.run_plan_id, planHash: m.artifact_hash,
      requestKey: crypto.randomUUID(), requestHash: await canonicalDigest(value.input) }
    buildRecovery.save(actorId, attempt); setStored({ attempt, invalid: false })
    return runPlanBuildApi.bind(value.input, attempt, (acknowledged) => {
      buildRecovery.acknowledge(actorId, acknowledged); setStored({ attempt: acknowledged, invalid: false })
    })
  }, onSettled: () => { setConsent(''); void client.invalidateQueries({ queryKey: [...prefix, 'original'] }) } })
  const recovery = useQuery({ ...sensitive, enabled: open && !!stored.attempt && !write.isPending,
    queryKey: [...prefix, 'original', stored.attempt?.requestKey, plan.current_use], queryFn: async ({ signal }) => {
      requireRunPlan(stored.attempt)
      const value = await runPlanBuildApi.recover(stored.attempt, plan, signal)
      const attempt = { ...stored.attempt, commandId: value.command.id }
      signal.throwIfAborted(); buildRecovery.acknowledge(actorId, attempt)
      return { ...value, attempt }
    }, refetchInterval: (query) => ['pending', 'running'].includes(query.state.data?.command.status ?? '') ? 10000 : false })
  const original = !write.isPending && !recovery.isFetching && !recovery.isError ? recovery.data : undefined
  const archive = useQuery({ ...sensitive, enabled: open && original?.command.status === 'completed',
    queryKey: [...prefix, 'archive', original?.command.id, plan.current_use], queryFn: ({ signal }) => {
      requireRunPlan(original)
      return runPlanBuildApi.read(original.command, original.input, plan, original.builds, signal)
    } })
  const denied = recovery.error instanceof ApiRequestError && [403, 502].includes(recovery.error.status)
  const failed = open && (archive.isError || denied)
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const busy = verify.isPending || write.isPending || recovery.isFetching || archive.isFetching
  const confirmationKey = JSON.stringify([prepared, original?.input, original?.command.status, recovery.dataUpdatedAt, plan.current_use, canBind])
  const confirmed = consent === confirmationKey && !!(prepared || original)
  const editable = !busy && !stored.attempt && !stored.invalid && canBind && !failed
  const mayPreview = editable && !write.isError && code.length > 0 && code.every((s) => scriptId(ids[s.binding_id]?.trim()))
    && new Set(Object.values(ids).map((v) => v.trim())).size === code.length && Object.values(ids).some((v) => v.trim() === target)
    && reason.trim().length > 0 && reason.length <= 4096
  const result = original && !archive.isFetching && !archive.isError ? archive.data : undefined
  const mayConfirmOriginal = !busy && !failed && canBind && original?.command.status === 'waiting_confirmation' && confirmed
  return { open, ids, target, reason, code, prepared, original, result, stored, confirmed, busy, failed, verify, write, recovery,
    editable, canBind, mayPreview, maySave: mayPreview && !!prepared && confirmed, mayConfirmOriginal,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    editId: (binding: string, value: string) => { if (editable) { setIds({ ...ids, [binding]: value }); setTarget(''); setConsent(''); verify.reset() } },
    editTarget: (value: string) => { if (editable) { setTarget(value); setConsent(''); verify.reset() } },
    editReason: (value: string) => { if (editable) { setReason(value); setConsent(''); verify.reset() } },
    preview: () => { if (mayPreview) { setConsent(''); verify.mutate() } },
    confirm: (checked: boolean) => setConsent(checked ? confirmationKey : ''),
    save: () => { if (mayPreview && prepared && confirmed && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ input: prepared.value.request }) } },
    confirmOriginal: () => { if (mayConfirmOriginal && original && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ attempt: original.attempt }) } },
    reload: () => { if (!busy) { setConsent(''); verify.reset(); submitted.current = false
      try { setStored({ attempt: buildRecovery.read(actorId, m.project_id, m.run_plan_id, m.artifact_hash), invalid: false }) }
      catch { setStored({ attempt: null, invalid: true }) }
      if (stored.attempt) void recovery.refetch(); if (original?.command.status === 'completed') void archive.refetch()
    } },
    another: () => { if (!busy && result && original) { buildRecovery.clear(actorId, original.attempt); setStored({ attempt: null, invalid: false });
      submitted.current = false; setConsent(''); verify.reset(); write.reset(); setTarget(''); setReason(''); setIds(Object.fromEntries(code.map((s) => [s.binding_id, '']))) } },
  }
}
