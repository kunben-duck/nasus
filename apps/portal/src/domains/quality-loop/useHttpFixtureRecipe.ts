import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { fixtureRecipeApi as api, fixtureRecipeRecovery as storage } from './httpFixtureRecipeApi'
import { parseFixtureRecipe } from './httpFixtureRecipeValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { FixtureRecipeAttempt } from './types/httpFixtureRecipes'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useHttpFixtureRecipe(plan: RunPlanArchive, actorId: string, current: boolean, onFailure: () => void) {
  const p = plan.metadata, client = useQueryClient(), submitted = useRef(false), draftRevision = useRef(0)
  const readStored = () => {
    try { return { attempt: storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  }
  const [open, setOpen] = useState(false), [text, setText] = useState(''), [consent, setConsent] = useState(''), [stored, setStored] = useState(readStored)
  const prefix = ['http-fixture-recipe', actorId, p.project_id, p.run_plan_id, p.artifact_hash]
  const canRegister = current && plan.current_use.inputs_current
  const preview = useMutation({ retry: false, mutationFn: async (source: string) => {
    const revision = draftRevision.current, request = await parseFixtureRecipe(plan, source)
    requireRunPlan(revision === draftRevision.current)
    return { source, request }
  }, onSettled: () => setConsent('') })
  const prepared = !stored.attempt && preview.data?.source === text && !preview.isPending && !preview.isError ? preview.data.request : undefined
  const write = useMutation({ retry: false, mutationFn: async (attempt?: FixtureRecipeAttempt) => {
    if (attempt) return api.confirm(attempt, plan)
    requireRunPlan(prepared)
    const value = { projectId: p.project_id, planId: p.run_plan_id, planHash: p.artifact_hash,
      requestKey: crypto.randomUUID(), requestHash: await canonicalDigest(prepared) }
    storage.save(actorId, value); setStored({ attempt: value, invalid: false })
    return api.register(prepared, value, plan, (ack) => { storage.acknowledge(actorId, ack); setStored({ attempt: ack, invalid: false }) })
  }, onSettled: () => { setConsent(''); void client.invalidateQueries({ queryKey: [...prefix, 'original'] }) } })
  const recovery = useQuery({ ...sensitive, enabled: open && !!stored.attempt && !write.isPending,
    queryKey: [...prefix, 'original', stored.attempt?.requestKey, plan.current_use], queryFn: async ({ signal }) => {
      requireRunPlan(stored.attempt)
      const original = await api.recover(stored.attempt, plan, signal), attempt = { ...stored.attempt, commandId: original.command.id }
      signal.throwIfAborted(); storage.acknowledge(actorId, attempt)
      return { ...original, attempt }
    }, refetchInterval: (q) => ['pending', 'running'].includes(q.state.data?.command.status ?? '') ? 10000 : false })
  const original = open && !write.isPending && !recovery.isFetching && !recovery.isError ? recovery.data : undefined
  const archive = useQuery({ ...sensitive, enabled: open && original?.command.status === 'completed',
    queryKey: [...prefix, 'archive', original?.command.id, plan.current_use], queryFn: ({ signal }) => {
      requireRunPlan(original); return api.read(original.command, plan, signal)
    } })
  const denied = recovery.isError && (!(recovery.error instanceof ApiRequestError) || [403, 502].includes(recovery.error.status))
  const failed = open && (archive.isError || denied)
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const busy = preview.isPending || write.isPending || recovery.isFetching || archive.isFetching
  const confirmationKey = JSON.stringify([prepared, original?.input, plan.current_use, canRegister, original?.command.id,
    original?.command.status, recovery.dataUpdatedAt])
  const confirmed = consent === confirmationKey
  const maySave = open && canRegister && !busy && !failed && !stored.invalid && !stored.attempt && !write.isError && !!prepared && confirmed
  const mayConfirm = open && canRegister && !busy && !failed && original?.command.status === 'waiting_confirmation' && confirmed
  const result = original && !archive.isFetching && !archive.isError ? archive.data : undefined
  return { open, text, prepared, stored, original, result, busy, failed, recovery, write, preview, canRegister, confirmed, maySave, mayConfirm,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    edit: (source: string) => { if (!busy && !stored.attempt && !stored.invalid) { draftRevision.current++; setText(source); setConsent(''); preview.reset() } },
    prepare: () => { if (open && canRegister && !busy && !stored.attempt && !stored.invalid && text.trim()) preview.mutate(text) },
    confirm: (checked: boolean) => setConsent(checked ? confirmationKey : ''),
    save: () => { if (maySave && !submitted.current) { submitted.current = true; setConsent(''); write.mutate(undefined) } },
    confirmOriginal: () => { if (mayConfirm && original && !submitted.current) { submitted.current = true; setConsent(''); write.mutate(original.attempt) } },
    reload: () => { if (!busy) { setConsent(''); submitted.current = false; setStored(readStored())
      if (stored.attempt) void recovery.refetch(); if (original?.command.status === 'completed') void archive.refetch()
    } },
    another: () => { if (!busy && result && original) { storage.clear(actorId, original.attempt); setStored({ attempt: null, invalid: false })
      submitted.current = false; draftRevision.current++; setConsent(''); setText(''); preview.reset(); write.reset()
    } },
  }
}
