import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { imageRevisionApi } from '../system-image/imageRevisionApi'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { verifyRunPlanAttempt } from './runPlanRecovery'
import { requireRunPlan, requestKeys, verifyRunPlanArchive, verifyRunPlanPreview } from './runPlanValidation'
import type { ToolInvocation } from '../platform/types'
import type { ScriptArchive, ScriptReviewArchive } from './types/automationScripts'
import type { RunPlanAttempt, RunPlanRequest, RunPlanSelection, RunPlanSources } from './types/runPlans'

export const runPlanTool = 'quality.run_plan.prepare'
export async function requireRunPlanCommand(value: ToolInvocation, attempt: RunPlanAttempt) {
  verifyRunPlanAttempt(attempt)
  const body = value?.input_payload, input = Object.fromEntries(requestKeys.map((key) => [key, body?.[key]])) as unknown as RunPlanRequest
  requireRunPlan(value && scriptId(value.id) && (!attempt.commandId || value.id === attempt.commandId) && value.tool_id === runPlanTool
    && body?.idempotency_key === attempt.requestKey && input.project_id === attempt.projectId
    && input.script_revision_id === attempt.scriptId && input.review_revision_id === attempt.reviewId
    && await canonicalDigest(input) === attempt.requestHash && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(value.status))
  if (value.status === 'completed') requireRunPlan(value.result?.invocation_id === value.id && value.result.status === 'completed'
    && body.confirmed_by_user === true && value.result.object_refs.length === 1 && value.result.object_refs[0].startsWith('run_plan:')
    && scriptId(value.result.object_refs[0].slice('run_plan:'.length)))
  return { command: value, input }
}
export async function readRunPlanSources(draft: ScriptArchive, signal: AbortSignal): Promise<RunPlanSources> {
  const p = draft.result.prepared, members: RunPlanSources['source_members'] = []
  let offset = 0, first: Awaited<ReturnType<typeof imageRevisionApi.page>> | undefined
  for (;;) {
    signal.throwIfAborted()
    const page = await imageRevisionApi.page(p.project_id, p.context_pin.image_revision_id, { section: 'source_members', offset }, signal, 25)
    requireRunPlan(page.section === 'source_members' && page.revision.artifact_hash === p.context_pin.image_artifact_hash
      && page.revision.project_id === p.project_id && page.revision.image_revision_id === p.context_pin.image_revision_id
      && generationDigest(page.revision.manifest_hash) && scriptId(page.revision.manifest_id) && page.total > 0 && page.total <= 1000
      && (!first || generationEqual(page.revision, first.revision) && page.total === first.total))
    first ??= page
    requireRunPlan(page.items.length <= 25 && offset + page.items.length <= page.total
      && page.next_offset === (offset + page.items.length < page.total ? offset + page.items.length : null)
      && (page.items.length > 0 || offset === page.total))
    for (const item of page.items) {
      requireRunPlan(scriptId(item.binding_id) && typeof item.source_type === 'string' && ['captured', 'failed', 'pending', 'legacy_unverified'].includes(item.status)
        && (item.status === 'captured' ? scriptId(item.source_revision_id) : item.source_revision_id === null)
        && !members.some((prior) => prior.binding_id === item.binding_id))
      members.push(item)
    }
    if (page.next_offset === null) break
    offset = page.next_offset
  }
  signal.throwIfAborted()
  return { project_id: p.project_id, image_revision_id: first!.revision.image_revision_id, image_artifact_hash: first!.revision.artifact_hash,
    manifest_id: first!.revision.manifest_id, manifest_hash: first!.revision.manifest_hash, source_members: members }
}
export const runPlanApi = {
  async preview(selection: RunPlanSelection, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources) {
    const command = await platformApi.invokeTool({ tool_id: 'query.quality.run_plan_preview', idempotency_key: crypto.randomUUID(), input: { ...selection } })
    requireRunPlan(scriptId(command?.id) && command.tool_id === 'query.quality.run_plan_preview' && command.status === 'completed'
      && Object.entries(selection).every(([key, value]) => generationEqual(command.input_payload[key], value)))
    return verifyRunPlanPreview(command.result?.run_plan_preview, selection, draft, review, sources)
  },
  async prepare(input: RunPlanRequest, attempt: RunPlanAttempt, acknowledge: (value: RunPlanAttempt) => void) {
    requireRunPlan(!attempt.commandId && await canonicalDigest(input) === attempt.requestHash)
    const pending = await requireRunPlanCommand(await platformApi.invokeTool({ tool_id: runPlanTool, idempotency_key: attempt.requestKey, input: { ...input } }), attempt)
    requireRunPlan(pending.command.status === 'waiting_confirmation')
    const fixed = { ...attempt, commandId: pending.command.id }; acknowledge(fixed)
    return this.confirm(fixed)
  },
  async confirm(attempt: RunPlanAttempt) {
    requireRunPlan(attempt.commandId)
    return requireRunPlanCommand(await platformApi.confirmToolInvocation(attempt.commandId), attempt)
  },
  async recover(attempt: RunPlanAttempt, signal: AbortSignal) {
    verifyRunPlanAttempt(attempt); signal.throwIfAborted()
    const value = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId,
        tool_id: runPlanTool, request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
    signal.throwIfAborted(); return requireRunPlanCommand(value, attempt)
  },
  async read(command: ToolInvocation, input: RunPlanRequest, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources, signal: AbortSignal) {
    requireRunPlan(command.status === 'completed' && command.result?.object_refs.length === 1)
    signal.throwIfAborted(); const id = command.result!.object_refs[0].slice('run_plan:'.length)
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/run-plans/${encodeURIComponent(id)}`, { signal, cache: 'no-store' })
    const archive = await verifyRunPlanArchive(value, input, command.id, draft, review, sources)
    requireRunPlan(archive.metadata.run_plan_id === id); signal.throwIfAborted(); return archive
  },
}
