import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { readFixtureEnvironment } from './httpFixtureEnvironmentApi'
import { fixtureOperationApi as api } from './httpFixtureOperationApi'
import { fixtureOperationRecovery as storage } from './httpFixtureOperationRecovery'
import { fixtureGrantRequest } from './httpFixtureOperationValidation'
import { identity } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { FixtureRecipeView } from './types/httpFixtureRecipes'
import type { FixtureCommandStage, FixtureOperation } from './types/httpFixtureOperations'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
type OperationFields = { environmentCommandId: string; attemptId: string; operation: FixtureOperation; timeoutMs: number }
type OperationWrite = { stage: FixtureCommandStage; confirm: boolean; input: Record<string, unknown>; fields: OperationFields }
export function useHttpFixtureOperation(plan: RunPlanArchive, recipe: FixtureRecipeView, actorId: string, current: boolean, onFailure: () => void) {
  const p = plan.metadata, r = recipe.metadata, client = useQueryClient(), submitted = useRef(false)
  const readStored = () => {
    try { return { attempt: storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash, r.record_id, r.artifact_hash), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  }
  const [open, setOpen] = useState(false), [stored, setStored] = useState(readStored), [consent, setConsent] = useState('')
  const [draft, setDraft] = useState({ environmentCommandId: '', attemptId: crypto.randomUUID() as string, operation: 'setup' as FixtureOperation, timeoutMs: 10000 })
  const [readEnvironmentId, setReadEnvironmentId] = useState('')
  const fields = stored.attempt ?? draft, prefix = ['http-fixture-operation', actorId, p.project_id, p.run_plan_id, p.artifact_hash, r.record_id, r.artifact_hash]
  const canOperate = fields.operation === 'cleanup' || current && plan.current_use.inputs_current
  const environment = useQuery({ ...sensitive, enabled: open && !stored.invalid && identity(fields.environmentCommandId)
    && (stored.attempt !== null || readEnvironmentId === fields.environmentCommandId),
    queryKey: [...prefix, 'environment', fields, plan.current_use], queryFn: async ({ signal }) => {
      const value = await readFixtureEnvironment(plan, fields.environmentCommandId, signal)
      const input = await fixtureGrantRequest(plan, recipe, value, fields); signal.throwIfAborted()
      return { value, input }
    } })
  const matching = environment.data?.input.attempt_id === fields.attemptId && environment.data.input.operation === fields.operation
    && environment.data.input.timeout_ms === fields.timeoutMs && environment.data.value.metadata.invocation_id === fields.environmentCommandId
  const prepared = open && !stored.invalid && matching && (stored.attempt !== null || readEnvironmentId === fields.environmentCommandId)
    && !environment.isFetching && !environment.isError ? environment.data : undefined
  const write = useMutation({ retry: false, mutationFn: async ({ stage, confirm, input, fields: selected }: OperationWrite) => {
    const requestHash = await canonicalDigest(input)
    let operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash, r.record_id, r.artifact_hash)
    if (!confirm) {
      const attempt = { requestKey: crypto.randomUUID(), requestHash }
      if (stage === 'grant') {
        requireRunPlan(!operation && !stored.invalid)
        operation = { projectId: p.project_id, planId: p.run_plan_id, planHash: p.artifact_hash, recipeId: r.record_id, recipeHash: r.artifact_hash,
          environmentCommandId: selected.environmentCommandId, attemptId: selected.attemptId, operation: selected.operation, timeoutMs: selected.timeoutMs, grant: attempt }
        storage.save(actorId, operation)
      } else { requireRunPlan(operation); operation = storage.add(actorId, operation, stage, attempt) }
      setStored({ attempt: operation, invalid: false })
    }
    requireRunPlan(operation && operation[stage])
    const attempt = operation[stage]!
    if (confirm) return api.confirm(stage, attempt, input, actorId)
    return api.submit(stage, attempt, input, actorId, (commandId) => {
      operation = storage.acknowledge(actorId, operation!, stage, commandId)
      setStored({ attempt: operation, invalid: false })
    })
  }, onSettled: () => { submitted.current = false; setConsent(''); void client.invalidateQueries({ queryKey: prefix }) } })
  const grant = useQuery({ ...sensitive, enabled: !!prepared && !!stored.attempt && !write.isPending,
    queryKey: [...prefix, 'grant', stored.attempt?.grant, prepared?.input], queryFn: async ({ signal }) => {
      requireRunPlan(prepared && stored.attempt)
      const command = await api.recover('grant', stored.attempt.grant, { ...prepared.input }, actorId, signal)
      const operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash, r.record_id, r.artifact_hash)
      signal.throwIfAborted(); requireRunPlan(operation); storage.acknowledge(actorId, operation, 'grant', command.id)
      const value = command.status === 'completed' ? await api.readGrant(command, prepared.input, plan, recipe, prepared.value, actorId, signal) : undefined
      signal.throwIfAborted(); return { command, grant: value }
    }, refetchInterval: (q) => ['pending', 'running'].includes(q.state.data?.command.status ?? '') ? 5000 : false })
  const grantResult = prepared && !write.isPending && !grant.isFetching && !grant.isError ? grant.data : undefined
  const execution = useQuery({ ...sensitive, enabled: !!grantResult?.grant && !!stored.attempt?.execute && !write.isPending,
    queryKey: [...prefix, 'execute', stored.attempt?.execute, grantResult?.grant], queryFn: async ({ signal }) => {
      requireRunPlan(grantResult?.grant && stored.attempt?.execute)
      const result = await api.readJob(stored.attempt.execute, grantResult.grant, recipe, actorId, signal)
      const operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash, r.record_id, r.artifact_hash)
      signal.throwIfAborted(); requireRunPlan(operation); storage.acknowledge(actorId, operation, 'execute', result.command.id)
      signal.throwIfAborted(); return result
    }, refetchInterval: (q) => q.state.data?.command.status === 'running' || q.state.data?.command.status === 'pending'
      || q.state.data?.job?.cancellation_requested && !q.state.data.job.cancellation_delivered ? 5000 : false })
  const executionResult = grantResult?.grant && !execution.isFetching && !execution.isError ? execution.data : undefined
  const cancellation = useQuery({ ...sensitive, enabled: !!executionResult && !!stored.attempt?.cancel && !write.isPending,
    queryKey: [...prefix, 'cancel', stored.attempt?.cancel, executionResult?.command.id], queryFn: async ({ signal }) => {
      requireRunPlan(executionResult && stored.attempt?.cancel)
      const input = { project_id: p.project_id, invocation_id: executionResult.command.id }
      const command = await api.recover('cancel', stored.attempt.cancel, input, actorId, signal)
      const operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash, r.record_id, r.artifact_hash)
      signal.throwIfAborted(); requireRunPlan(operation); storage.acknowledge(actorId, operation, 'cancel', command.id)
      signal.throwIfAborted(); return command
    }, refetchInterval: (q) => ['pending', 'running'].includes(q.state.data?.status ?? '') ? 5000 : false })
  const cancellationResult = executionResult && !cancellation.isFetching && !cancellation.isError ? cancellation.data : undefined
  const queries = [environment, grant, execution, cancellation]
  const busy = write.isPending || queries.some((q) => q.isFetching)
  const unavailable = stored.invalid || queries.some((q) => q.isError)
  const failed = open && queries.some((q) => q.isError && (!(q.error instanceof ApiRequestError) || [403, 502].includes(q.error.status)))
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const confirmationKey = JSON.stringify([prepared?.input, plan.current_use, current, grantResult, executionResult, cancellationResult,
    environment.dataUpdatedAt, grant.dataUpdatedAt, execution.dataUpdatedAt, cancellation.dataUpdatedAt])
  const confirmed = (stage: FixtureCommandStage) => consent === stage + confirmationKey
  const mayWrite = (stage: FixtureCommandStage) => {
    if (!open || !prepared || busy || unavailable || failed || !confirmed(stage) || write.isError) return false
    if (stage === 'grant') return canOperate && (!stored.attempt || grantResult?.command.status === 'waiting_confirmation')
    if (stage === 'execute') return canOperate && !!grantResult?.grant && (!stored.attempt?.execute || executionResult?.command.status === 'waiting_confirmation')
    return executionResult?.command.status === 'running' && (!stored.attempt?.cancel || cancellationResult?.status === 'waiting_confirmation')
  }
  return { open, fields, stored, prepared, busy, failed, unavailable, canOperate, grant: grantResult, execution: executionResult,
    cancellation: cancellationResult, write, confirmed, mayWrite,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    edit: (patch: Partial<typeof draft>) => { if (!busy && !stored.attempt && !stored.invalid) { setDraft({ ...draft, ...patch }); setReadEnvironmentId(''); setConsent('') } },
    verifyEnvironment: () => { if (!busy && !stored.invalid && identity(fields.environmentCommandId)) { setReadEnvironmentId(fields.environmentCommandId); setConsent('') } },
    confirm: (stage: FixtureCommandStage, checked: boolean) => setConsent(checked ? stage + confirmationKey : ''),
    submit: (stage: FixtureCommandStage) => { if (mayWrite(stage) && !submitted.current) {
      const command = stage === 'grant' ? grantResult?.command : stage === 'execute' ? executionResult?.command : cancellationResult
      const input: Record<string, unknown> = stage === 'grant' ? { ...prepared!.input } : stage === 'execute'
        ? { project_id: p.project_id, grant_id: grantResult!.grant!.metadata.record_id, grant_digest: grantResult!.grant!.metadata.grant_digest, operation: fields.operation }
        : { project_id: p.project_id, invocation_id: executionResult!.command.id }
      // Pending writes disable sensitive queries. Capture verified inputs before their keys/data disappear.
      const selected = { environmentCommandId: fields.environmentCommandId, attemptId: fields.attemptId, operation: fields.operation, timeoutMs: fields.timeoutMs }
      submitted.current = true; setConsent(''); write.mutate({ stage, confirm: command?.status === 'waiting_confirmation', input, fields: selected })
    } },
    reload: () => { if (!busy) { setConsent(''); setStored(readStored()); write.reset(); void client.invalidateQueries({ queryKey: prefix }) } },
    next: () => { if (!busy && stored.attempt && executionResult?.job?.status === 'completed'
      && executionResult.job.phases.every((item) => item.state === 'observed') && !unavailable) {
      const operation = storage.read(actorId, p.project_id, p.run_plan_id, p.artifact_hash, r.record_id, r.artifact_hash)
      requireRunPlan(operation); storage.clear(actorId, operation)
      setDraft({ environmentCommandId: operation.environmentCommandId, attemptId: operation.operation === 'setup' ? operation.attemptId : crypto.randomUUID(),
        operation: operation.operation === 'setup' ? 'cleanup' : 'setup', timeoutMs: operation.timeoutMs })
      setStored({ attempt: null, invalid: false }); setReadEnvironmentId(''); setConsent(''); write.reset()
    } },
  }
}
