import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { generationEqual } from './testDesignGenerationValidation'
import { mappingInvariant, prepareMappingPlan } from './testDesignMappingPartitions'
import { mappingId, mappingQuery, originalPart, verifyPartHead, verifyStagedArchive } from './mappingStagingValidation'
import { verifyFinalPreview } from './mappingFinalPreviewValidation'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { MappingPlan } from './types/testDesignMapping'
import type { MappingWorkspace, MappingPartView, MappingPartCommand, StagedPartRevision } from './types/mappingStaging'
import type { ToolInvocation } from '../platform/types'

export class MappingPartChanged extends Error {}
function resultPath(plan: MappingPlan) {
  const pin = plan.generation_pin
  return `/v1/projects/${encodeURIComponent(pin.project_id)}/quality/test-design-results/${encodeURIComponent(pin.generation_id)}`
}
function params(workspace: MappingWorkspace) {
  return new URLSearchParams({ artifact_hash: workspace.plan.generation_pin.artifact_hash, plan_digest: workspace.plan.plan_digest })
}
function exact(command: ToolInvocation, tool: string, input: MappingPartCommand) {
  return command && command.tool_id === tool && mappingId(command.id)
    && Object.entries(input).every(([key, value]) => generationEqual(command.input_payload?.[key], value))
}
export const mappingStagingApi = {
  async open(draft: GenerationArchive, previous: string | null, scopeCurrent: boolean, signal: AbortSignal): Promise<MappingWorkspace> {
    const user = await request<{ id: string }>('/v1/auth/me', { signal, cache: 'no-store' }), m = draft.metadata
    mappingInvariant(mappingId(user.id))
    const { plan, partDigests } = await prepareMappingPlan(draft, previous)
    const value = await request<Record<string, unknown>>(`${resultPath(plan)}/mapping-plan?${new URLSearchParams({ artifact_hash: m.artifact_hash })}`,
      { signal, cache: 'no-store' })
    mappingInvariant(Object.keys(value).length === 9 && generationEqual(value.plan, plan) && value.part === null
      && value.project_id === m.project_id && value.generation_id === m.generation_id && value.generation_artifact_hash === m.artifact_hash
      && value.scope_current === scopeCurrent && value.historical_not_live === true && value.review_authorized === false && value.execution_authorized === false)
    signal.throwIfAborted(); return { plan, partDigests, actorId: user.id, scopeCurrent }
  },
  async part(draft: GenerationArchive, workspace: MappingWorkspace, sequence: number, signal: AbortSignal): Promise<MappingPartView> {
    const part = originalPart(draft, workspace, sequence), query = params(workspace), path = `${resultPath(workspace.plan)}/mapping-parts/${sequence}`
    const value = await request<Record<string, unknown>>(`${path}?${query}`, { signal, cache: 'no-store' })
    mappingInvariant(Object.keys(value).length === 9 && generationEqual(value.plan, workspace.plan) && generationEqual(value.part, part)
      && Object.entries(mappingQuery(workspace)).every(([k, x]) => value[k] === x) && value.scope_current === workspace.scopeCurrent
      && value.historical_not_live === true && value.review_authorized === false && value.execution_authorized === false)
    const head = verifyPartHead(await request<unknown>(`${path}/staged?${query}`, { signal, cache: 'no-store' }), workspace, part)
    const archive = head.head ? await this.read(workspace, part, head.head, signal) : null
    if (archive && archive.current_use.part_current !== workspace.scopeCurrent) throw new MappingPartChanged('Private part head changed')
    signal.throwIfAborted(); return { part, head, archive }
  },
  async read(workspace: MappingWorkspace, part: MappingPartView['part'], revision: StagedPartRevision, signal: AbortSignal) {
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(workspace.plan.generation_pin.project_id)}/quality/test-design-mapping-parts/${encodeURIComponent(revision.part_revision_id)}`,
      { signal, cache: 'no-store' })
    const archive = await verifyStagedArchive(value, workspace, part, revision)
    signal.throwIfAborted(); return archive
  },
  async preview(workspace: MappingWorkspace, signal: AbortSignal) {
    const value = await request<unknown>(`${resultPath(workspace.plan)}/mapping-finalization?${params(workspace)}`, { signal, cache: 'no-store' })
    const preview = await verifyFinalPreview(value, workspace)
    signal.throwIfAborted(); return preview
  },
  async record(input: MappingPartCommand, attempt: string) {
    const staged = input.policy_revision === 'nasus.test-design-mapping-staging.v1'
    const tool = staged ? 'quality.test_design_mapping.stage_part' : 'quality.test_design_mapping.finalize'
    const pending = await platformApi.invokeTool({ tool_id: tool, input: { ...input }, idempotency_key: attempt })
    if (!exact(pending, tool, input) || pending.status !== 'waiting_confirmation') throw new Error('Exact independent confirmation required')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.result?.followup_reason === 'test_design_mapping_changed') throw new MappingPartChanged('Mapping inputs changed')
    const refs = done.result?.object_refs, prefix = staged ? 'test_design_mapping_part:' : 'test_design_mapping:'
    if (done.id !== pending.id || !exact(done, tool, input) || done.status !== 'completed' || done.input_payload.confirmed_by_user !== true
      || !Array.isArray(refs) || refs.length !== 1 || typeof refs[0] !== 'string' || !refs[0].startsWith(prefix) || !mappingId(refs[0].slice(prefix.length))) {
      throw new Error('Mapping command was not acknowledged; inspect history before any new command')
    }
    return { invocationId: done.id, revisionId: refs[0].slice(prefix.length) }
  },
}
