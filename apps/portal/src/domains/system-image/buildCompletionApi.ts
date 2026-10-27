import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { completionReviewStep, validReviewHash, validReviewId, type BuildReviewHandoff } from './buildReviewHandoff'
import type { BuildCompletionCommand, BuildCompletionInput, BuildCompletionObservation, BuildCompletionPointer, BuildCompletionReport } from './types/buildCompletion'

const toolId = 'query.system_image.build_completion.read'
const equal = async (left: unknown, right: unknown) => await canonicalDigest(left) === await canonicalDigest(right)
const count = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

export function parseCompletionPointer(params: URLSearchParams): BuildCompletionPointer | null {
  const keys = params.getAll('build_completion_request'), ids = params.getAll('build_completion_invocation')
  if (!keys.length && !ids.length) return null
  if (keys.length !== 1 || ids.length > 1 || !validReviewId(keys[0]) || (ids.length && !validReviewId(ids[0]))) {
    throw new Error('Invalid completion assessment pointer')
  }
  return { requestKey: keys[0], invocationId: ids[0] ?? null }
}

export function completionInput(review: BuildReviewHandoff): BuildCompletionInput {
  if (review.goal.project_id !== review.projectId || review.goal.id !== review.selection.goalId
      || completionReviewStep(review.goal)?.tool_invocation_id !== review.selection.invocationId
      || review.goal.active_started_at != null) throw new Error('Completion requires the original settled build review')
  return { project_id: review.projectId, investigation_revision_id: review.investigation.revision_id,
    investigation_revision_hash: review.investigation.revision_hash, expected_goal: review.goal,
    analyses: [], analysis_policy: 'committed_build' }
}

export async function validateCompletionCommand(command: BuildCompletionCommand, review: BuildReviewHandoff,
  pointer: BuildCompletionPointer): Promise<BuildCompletionCommand> {
  const input = completionInput(review)
  if (!command || !validReviewId(command.id) || (pointer.invocationId !== null && command.id !== pointer.invocationId)
      || command.tool_id !== toolId || command.conversation_id !== review.goal.conversation_id
      || !['pending', 'running', 'completed', 'failed', 'cancelled'].includes(command.status)
      || command.input_payload?.idempotency_key !== pointer.requestKey
      || !await equal(Object.fromEntries(Object.entries(command.input_payload).filter(([key]) => key !== 'idempotency_key')), input)
      || (command.result && (command.result.invocation_id !== command.id || command.result.status !== command.status))) {
    throw new Error('Completion command differs from the original request')
  }
  if (command.status === 'completed') {
    const receipt = command.result?.build_completion
    if (receipt?.kind !== 'build_completion' || receipt.project_id !== input.project_id
        || receipt.investigation_revision_id !== input.investigation_revision_id
        || receipt.investigation_revision_hash !== input.investigation_revision_hash
        || !validReviewHash(receipt.report_hash) || receipt.request_hash !== await canonicalDigest(input)
        || !await equal(command.result?.object_refs, [`build_completion:${command.id}`])) {
      throw new Error('Completion receipt differs from the original request')
    }
  }
  return command
}

export async function validateCompletionReport(report: BuildCompletionReport, command: BuildCompletionCommand,
  review: BuildReviewHandoff): Promise<BuildCompletionReport> {
  const receipt = command.result?.build_completion, input = completionInput(review)
  const clock = review.goal.active_runtime_ms != null
  const checkpointDigest = await canonicalDigest({ schema: `nasus.agent-resume-checkpoint.v${clock ? 2 : 1}`, goal: review.goal })
  if (!report || !receipt || await canonicalDigest(report) !== receipt.report_hash
      || report.schema !== 'nasus.image-build-completion.v2' || report.project_id !== review.projectId
      || report.investigation_revision_id !== input.investigation_revision_id
      || report.investigation_revision_hash !== input.investigation_revision_hash
      || report.plan_digest !== review.investigation.request.plan_digest
      || report.image_revision_id !== review.image.image_revision_id || report.image_artifact_hash !== review.image.artifact_hash
      || report.source_manifest_id !== review.image.manifest_id || report.source_manifest_hash !== review.image.manifest_hash
      || report.goal_checkpoint?.goal_id !== review.goal.id || report.goal_checkpoint?.project_id !== review.projectId
      || report.goal_checkpoint?.conversation_id !== review.goal.conversation_id
      || report.goal_checkpoint?.workflow_id !== (review.goal.workflow_id ?? null) || report.goal_checkpoint?.digest !== checkpointDigest
      || report.state !== 'blocked' || report.delivery_kind !== 'candidate_only'
      || [report.candidate_ready, report.goal_completed, report.publication_authorized, report.execution_authorized].some((flag) => flag !== false)
      || !Array.isArray(report.blockers) || !report.blockers.length || report.blockers.some((code) => !validReviewId(code))
      || !Array.isArray(report.gaps) || report.gaps.some((gap) => !validReviewId(gap.code)
        || typeof gap.reason !== 'string' || typeof gap.required_action !== 'string' || gap.owner_actor_id !== null)
      || !Array.isArray(report.source_scans) || report.source_scans.some((scan) => !validReviewId(scan.source_revision_id)
        || !count(scan.file_count) || scan.file_bodies_verified !== true || scan.verified_file_count !== scan.file_count || !count(scan.verified_byte_count))
      || !Array.isArray(report.code_analyses) || report.code_analyses.some((analysis) => !validReviewId(analysis.source_revision_id)
        || !validReviewId(analysis.analysis_id) || !validReviewHash(analysis.report_hash) || !count(analysis.file_count))
      || !Array.isArray(report.build_lineages) || report.build_lineages.some((lineage) => !validReviewId(lineage.invocation_id)
        || !Array.isArray(lineage.analyses) || lineage.analyses.some((analysis) => !validReviewId(analysis.source_revision_id)
          || !validReviewId(analysis.analysis_id) || (analysis.native !== null && !validReviewId(analysis.native?.generation?.generation_id))
          || !Array.isArray(analysis.unused_native_generations) || analysis.unused_native_generations.some((pin) => !validReviewId(pin.generation_id))))
      || !['structure', 'behavior', 'traceability', 'automation', 'execution'].every((key) => {
        const dimension = report.readiness?.[key as keyof typeof report.readiness]
        return dimension && typeof dimension.state === 'string' && dimension.coverage === null
      })
      || !count(report.readiness.structure.verified_evidence_count)
      || !report.budget || report.budget.full_plan_accounting_verified !== false || report.budget.cost_microusd !== null
      || ![report.budget.goal_model_calls_used, report.budget.goal_thinking_tokens_used, report.budget.goal_steps_completed].every(count)
      || (report.budget.goal_active_runtime_ms !== null && !count(report.budget.goal_active_runtime_ms))
      || report.critical_conflicts?.state !== 'unverified' || report.critical_conflicts.count !== null) {
    throw new Error('Completion report failed fixed-scope and integrity verification')
  }
  return report
}

export const buildCompletionApi = {
  async prepare(review: BuildReviewHandoff, pointer: BuildCompletionPointer) {
    if (!validReviewId(pointer.requestKey) || pointer.invocationId !== null) throw new Error('A new completion assessment requires a fresh request pointer')
    const input = completionInput(review)
    const command = await platformApi.invokeTool({ tool_id: toolId, conversation_id: review.goal.conversation_id,
      idempotency_key: pointer.requestKey, input: { ...input } })
    return validateCompletionCommand(command, review, pointer)
  },
  async read(review: BuildReviewHandoff, pointer: BuildCompletionPointer, signal: AbortSignal): Promise<BuildCompletionObservation> {
    signal.throwIfAborted()
    completionInput(review)
    let id = pointer.invocationId
    if (id === null) {
      // Recover a lost acknowledgement by its original key, never by newest
      // command and never by resubmitting the query.
      const params = new URLSearchParams({ conversation_id: review.goal.conversation_id, tool_id: toolId })
      const commands = await request<BuildCompletionCommand[]>(`/v1/tool-invocations?${params}`, { signal, cache: 'no-store' })
      if (!Array.isArray(commands) || commands.length > 256) throw new Error('Completion discovery exceeded its complete bound')
      const matches = commands.filter((command) => command.input_payload?.idempotency_key === pointer.requestKey)
      if (matches.length !== 1) throw new Error('Original completion acknowledgement could not be verified')
      id = matches[0].id
    }
    const command = await validateCompletionCommand(await platformApi.getToolInvocation(id, { signal }), review, { ...pointer, invocationId: id })
    const report = command.status === 'completed' ? await validateCompletionReport(await request<BuildCompletionReport>(
      `/v1/projects/${encodeURIComponent(review.projectId)}/system-image/build-completions/${encodeURIComponent(id)}`,
      { signal, cache: 'no-store' }), command, review) : null
    const current = await request(`/v1/agent-goals/${encodeURIComponent(review.goal.id)}`, { signal, cache: 'no-store' })
    signal.throwIfAborted()
    if (!await equal(current, review.goal)) throw new Error('The original build checkpoint changed during completion verification')
    return { command, report }
  },
}
