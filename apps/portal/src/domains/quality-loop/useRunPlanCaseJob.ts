import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import { caseControlInput, requireCaseFields, requireCaseParent } from './runPlanCaseValidation'
import { caseExecutionApi as api } from './runPlanCaseApi'
import { caseRecovery as storage } from './runPlanCaseRecovery'
import type { RunPlanArchive } from './types/runPlans'
import type { CaseCommandStage, CaseExecutionFields, CaseExecutionSelection } from './types/runPlanCaseJobs'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
type Write = { stage: CaseCommandStage; confirm: boolean; input: Record<string, unknown>; fields: CaseExecutionFields }
export function useRunPlanCaseJob(plan: RunPlanArchive, actorId: string, current: boolean, onFailure: () => void) {
  const p = plan.metadata, client = useQueryClient(), submitted = useRef(false)
  const readStored = () => {
    try { return { attempt: storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  }
  const [stored, setStored] = useState(readStored), [open, setOpen] = useState(false), [consent, setConsent] = useState('')
  const [verifiedFields, setVerifiedFields] = useState('')
  const [draft, setDraft] = useState<CaseExecutionFields>({ runId: crypto.randomUUID(), environmentCommandId: '', locatorCommandId: '', timeoutMs: 10000,
    setups: plan.artifact.plan.prepared.cases.map((v) => ({ caseId: v.case_id, commandId: '' })) })
  const fields = stored.attempt?.fields ?? draft, prefix = ['run-plan-case-execution', actorId, p.project_id, p.run_plan_id, p.artifact_hash]
  const canExecute = current && plan.current_use.inputs_current
  let complete = false
  try { requireCaseFields(fields, plan); complete = true } catch { /* Incomplete inputs never trigger a read or write. */ }
  const references = useQuery({ ...sensitive, queryKey: [...prefix, 'references', fields],
    enabled: open && complete && !stored.attempt && !stored.invalid && verifiedFields === JSON.stringify(fields),
    queryFn: async ({ signal }) => ({ fields, input: await api.prepare(plan, fields, signal) }) })
  const prepared = open && !stored.attempt && !references.isError && !references.isFetching && references.data
    && generationEqual(references.data.fields, fields) ? references.data.input : undefined
  const write = useMutation({ retry: false, mutationFn: async ({ stage, confirm, input, fields: fixed }: Write) => {
    const requestHash = await canonicalDigest(input)
    let operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash)
    if (!confirm) {
      if (stage === 'execute') {
        requireRunPlan(!operation && !stored.invalid)
        const selection = input as unknown as CaseExecutionSelection
        requireCaseFields(fixed, plan); requireCaseParent(selection, plan)
        operation = storage.save(actorId, { projectId: p.project_id, planId: p.run_plan_id, planHash: p.artifact_hash,
          fields: fixed, input: selection, execute: { requestKey: crypto.randomUUID(), requestHash } })
      } else {
        requireRunPlan(operation)
        operation = storage.addCancel(actorId, operation, crypto.randomUUID(), requestHash)
      }
      setStored({ attempt: operation, invalid: false })
    }
    requireRunPlan(operation && operation[stage])
    const a = operation[stage]!
    if (confirm) return api.confirm(stage, a, input, actorId)
    return api.submit(stage, a, input, actorId, (id) => {
      operation = storage.acknowledge(actorId, operation!, stage, id)
      setStored({ attempt: operation, invalid: false })
    })
  }, onSettled: () => { submitted.current = false; setConsent(''); void client.invalidateQueries({ queryKey: prefix }) } })
  const execution = useQuery({ ...sensitive, queryKey: [...prefix, 'original', stored.attempt], enabled: open && !!stored.attempt && !write.isPending,
    queryFn: async ({ signal }) => {
      requireRunPlan(stored.attempt)
      const original = await api.read(stored.attempt.execute, stored.attempt.input, plan, actorId, signal)
      signal.throwIfAborted()
      const operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash)
      requireRunPlan(operation); storage.acknowledge(actorId, operation, 'execute', original.command.id)
      return original
    }, refetchInterval: (q) => ['pending', 'running'].includes(q.state.data?.command.status ?? '') ? 5000 : false })
  const original = !execution.isError && !execution.isFetching && !write.isPending ? execution.data : undefined
  const cancellation = useQuery({ ...sensitive, queryKey: [...prefix, 'cancel', stored.attempt?.cancel, original?.command.id],
    enabled: open && !!stored.attempt?.cancel && !!original && !write.isPending,
    queryFn: async ({ signal }) => {
      requireRunPlan(stored.attempt?.cancel && original)
      const input = caseControlInput(stored.attempt.input, original.command.id)
      const command = await api.recover('cancel', stored.attempt.cancel, input, actorId, signal)
      signal.throwIfAborted()
      const operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash)
      requireRunPlan(operation); storage.acknowledge(actorId, operation, 'cancel', command.id)
      return command
    }, refetchInterval: (q) => ['pending', 'running'].includes(q.state.data?.status ?? '') ? 5000 : false })
  const control = original && !cancellation.isError && !cancellation.isFetching ? cancellation.data : undefined
  const queries = [references, execution, cancellation], busy = write.isPending || queries.some((q) => q.isFetching)
  const unavailable = stored.invalid || queries.some((q) => q.isError)
  const failed = open && queries.some((q) => q.isError && (!(q.error instanceof ApiRequestError) || [403, 409, 502].includes(q.error.status)))
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const confirmationKey = JSON.stringify([fields, prepared, original, control, current, plan.current_use,
    references.dataUpdatedAt, execution.dataUpdatedAt, cancellation.dataUpdatedAt])
  const confirmed = (stage: CaseCommandStage) => consent === stage + confirmationKey
  const mayWrite = (stage: CaseCommandStage) => {
    if (!open || busy || unavailable || failed || !confirmed(stage)) return false
    if (stage === 'execute') return canExecute && ((!stored.attempt && !!prepared) || original?.command.status === 'waiting_confirmation')
    return original?.command.status === 'running' && (!stored.attempt?.cancel || control?.status === 'waiting_confirmation')
  }
  return { open, fields, stored, prepared, busy, unavailable, failed, canExecute,
    canVerify: open && complete && !busy && !stored.attempt && !stored.invalid,
    original: failed || unavailable ? undefined : original,
    control: failed || unavailable ? undefined : control, write, confirmed, mayWrite,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    edit: (patch: Partial<CaseExecutionFields>) => { if (!busy && !stored.attempt && !stored.invalid) {
      setDraft({ ...draft, ...patch }); setVerifiedFields(''); setConsent('')
    } },
    verify: () => { if (!busy && complete && !stored.attempt && !stored.invalid) { setVerifiedFields(JSON.stringify(fields)); setConsent('') } },
    confirm: (stage: CaseCommandStage, checked: boolean) => setConsent(checked ? stage + confirmationKey : ''),
    reload: () => { if (!busy) { setConsent(''); setStored(readStored()); write.reset(); void client.invalidateQueries({ queryKey: prefix }) } },
    submit: (stage: CaseCommandStage) => { if (mayWrite(stage) && !submitted.current) {
      const command = stage === 'execute' ? original?.command : control
      const input = stage === 'execute' ? { ...(stored.attempt?.input ?? prepared!) }
        : caseControlInput(stored.attempt!.input, original!.command.id)
      submitted.current = true; setConsent(''); write.mutate({ stage, confirm: command?.status === 'waiting_confirmation', input, fields: structuredClone(fields) })
    } },
  }
}
