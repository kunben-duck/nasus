import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { readRunPlanSources, runPlanApi } from './runPlanApi'
import { emptyRunPlanFields, runPlanFieldsValid, runPlanSelection } from './runPlanDraft'
import { runPlanRecovery } from './runPlanRecovery'
import { expectedRunPlan, planSelection, requireRunPlan } from './runPlanValidation'
import type { ScriptArchive, ScriptReviewArchive } from './types/automationScripts'
import type { RunPlanAttempt, RunPlanFields, RunPlanRequest } from './types/runPlans'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useRunPlan(draft: ScriptArchive, review: ScriptReviewArchive, actorId: string, current: boolean, onFailure: () => void) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false), [fields, setFields] = useState(() => emptyRunPlanFields(draft)), [consent, setConsent] = useState('')
  const [stored, setStored] = useState(() => { try { return { attempt: runPlanRecovery.read(actorId, draft.metadata.project_id, draft.metadata.script_revision_id, review.revision.revision_id), invalid: false } }
    catch { return { attempt: null, invalid: true } } })
  const submitted = useRef(false), m = draft.metadata, prefix = ['run-plans', m.project_id, actorId, m.script_revision_id, review.revision.revision_id]
  const sources = useQuery({ ...sensitive, enabled: open, queryKey: [...prefix, 'sources', draft.result.prepared.context_pin],
    queryFn: ({ signal }) => readRunPlanSources(draft, signal) })
  const source = !sources.isFetching && !sources.isError ? sources.data : undefined
  const canPrepare = current && draft.current_use.input_current && review.revision.status === 'reviewed' && review.assessment?.review_complete === true
  const key = JSON.stringify([fields, source, review, canPrepare])
  const preview = useMutation({ retry: false, mutationFn: async () => {
    requireRunPlan(source && canPrepare)
    const selection = await runPlanSelection(fields, draft, review, source)
    return { key, value: await runPlanApi.preview(selection, draft, review, source) }
  } })
  const prepared = source && canPrepare && preview.data?.key === key && !preview.isError ? preview.data.value : undefined
  const write = useMutation({ retry: false, mutationFn: async (value: { input: RunPlanRequest } | { attempt: RunPlanAttempt }) => {
    if ('attempt' in value) return runPlanApi.confirm(value.attempt)
    const attempt = { projectId: m.project_id, scriptId: m.script_revision_id, reviewId: review.revision.revision_id,
      requestKey: crypto.randomUUID(), requestHash: await canonicalDigest(value.input) }
    runPlanRecovery.save(actorId, attempt); setStored({ attempt, invalid: false })
    return runPlanApi.prepare(value.input, attempt, (acknowledged) => {
      runPlanRecovery.acknowledge(actorId, acknowledged); setStored({ attempt: acknowledged, invalid: false })
    })
  }, onSettled: () => { setConsent(''); void client.invalidateQueries({ queryKey: [...prefix, 'original'] }) } })
  const recovery = useQuery({ ...sensitive, enabled: open && !!stored.attempt && !!source && !write.isPending,
    queryKey: [...prefix, 'original', stored.attempt?.requestKey, source], queryFn: async ({ signal }) => {
      requireRunPlan(stored.attempt && source)
      const value = await runPlanApi.recover(stored.attempt, signal)
      const plan = await expectedRunPlan(planSelection(value.input), draft, review, source)
      requireRunPlan(plan.plan_digest === value.input.plan_digest)
      signal.throwIfAborted(); const attempt = { ...stored.attempt, commandId: value.command.id }
      runPlanRecovery.acknowledge(actorId, attempt)
      return { ...value, attempt }
    }, refetchInterval: (query) => ['pending', 'running'].includes(query.state.data?.command.status ?? '') ? 10000 : false })
  const original = source && !write.isPending && !recovery.isFetching && !recovery.isError ? recovery.data : undefined
  const archive = useQuery({ ...sensitive, enabled: open && !!source && original?.command.status === 'completed',
    queryKey: [...prefix, 'archive', original?.command.id, source, current], queryFn: async ({ signal }) => {
      requireRunPlan(original && source)
      const value = await runPlanApi.read(original.command, original.input, draft, review, source, signal)
      requireRunPlan(!value.current_use.inputs_current || current)
      return value
    } })
  const failed = open && (sources.isError || archive.isError)
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const busy = sources.isFetching || preview.isPending || write.isPending || recovery.isFetching || archive.isFetching
  const confirmationKey = JSON.stringify([prepared, original?.input, original?.command.status, sources.dataUpdatedAt, recovery.dataUpdatedAt, canPrepare])
  const confirmed = consent === confirmationKey && !!(prepared || original)
  const mayPreview = open && !busy && !stored.invalid && !stored.attempt && !write.isError && canPrepare && !!source && runPlanFieldsValid(fields, draft)
  const result = original && !archive.isFetching && !archive.isError ? archive.data : undefined
  const mayConfirmOriginal = !busy && !failed && canPrepare && original?.command.status === 'waiting_confirmation' && confirmed
  return { open, fields, source, prepared, original, result, confirmed, busy, failed, stored, preview, write, recovery,
    canPrepare, mayPreview, maySave: mayPreview && !!prepared && confirmed, mayConfirmOriginal,
    toggle: () => { if (!write.isPending) { setOpen(!open); setConsent('') } },
    edit: (value: Partial<RunPlanFields>) => { if (!busy && !stored.attempt && !stored.invalid) { setFields({ ...fields, ...value }); setConsent(''); preview.reset() } },
    prepare: () => { if (mayPreview) { setConsent(''); preview.mutate() } },
    confirm: (checked: boolean) => setConsent(checked ? confirmationKey : ''),
    save: () => { if (mayPreview && prepared && confirmed && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ input: prepared.request }) } },
    confirmOriginal: () => { if (mayConfirmOriginal && original && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ attempt: original.attempt }) } },
    reload: () => { if (!write.isPending) {
      setConsent(''); preview.reset(); submitted.current = false
      try { setStored({ attempt: runPlanRecovery.read(actorId, m.project_id, m.script_revision_id, review.revision.revision_id), invalid: false }) }
      catch { setStored({ attempt: null, invalid: true }) }
      void sources.refetch(); if (stored.attempt) void recovery.refetch(); if (original?.command.status === 'completed') void archive.refetch()
    } },
    another: () => { if (!busy && result && original) { runPlanRecovery.clear(actorId, original.attempt); setStored({ attempt: null, invalid: false });
      submitted.current = false; setConsent(''); preview.reset(); write.reset(); setFields(emptyRunPlanFields(draft)) } },
  }
}
