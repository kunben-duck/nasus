import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { completionInput } from './buildCompletionApi'
import { buildGapOwnershipApi, validateGapOwnership } from './buildGapOwnershipApi'
import { validReviewHash, validReviewId, type BuildReviewHandoff } from './buildReviewHandoff'
import type { BuildCompletionCommand, BuildCompletionObservation, BuildCompletionPointer, CompletionOwnershipPin,
  OwnedBuildCompletionInput, OwnedBuildCompletionObservation, OwnedBuildCompletionReport } from './types/buildCompletion'
import type { GapOwnershipView } from './types/buildGapOwnership'

const toolId = 'query.system_image.build_completion.read'
const equal = async (a: unknown, b: unknown) => await canonicalDigest(a) === await canonicalDigest(b)

export function parseOwnedCompletionPointer(params: URLSearchParams): BuildCompletionPointer | null {
  const keys = params.getAll('build_owned_completion_request'), ids = params.getAll('build_owned_completion_invocation')
  if (!keys.length && !ids.length) return null
  if (keys.length !== 1 || ids.length > 1 || !validReviewId(keys[0]) || ids.length && !validReviewId(ids[0])) {
    throw new Error('Invalid responsibility-pinned completion pointer')
  }
  return { requestKey: keys[0], invocationId: ids[0] ?? null }
}

function selectedRevision(view: GapOwnershipView, completion: BuildCompletionObservation, pin: CompletionOwnershipPin) {
  if (!pin || Object.keys(pin).sort().join(',') !== 'completion_invocation_id,completion_report_hash,revision_hash,revision_id'
      || pin.completion_invocation_id !== completion.command.id || pin.completion_report_hash !== view.completion_report_hash
      || !validReviewId(pin.revision_id) || !validReviewHash(pin.revision_hash)) throw new Error('Invalid fixed responsibility pin')
  const revision = view.history.find((item) => item.revision_id === pin.revision_id && item.revision_hash === pin.revision_hash)
  if (!revision) throw new Error('The exact confirmed responsibility revision is unavailable')
  return revision
}

export async function ownedCompletionInput(review: BuildReviewHandoff, completion: BuildCompletionObservation,
  view: GapOwnershipView, pin?: CompletionOwnershipPin): Promise<OwnedBuildCompletionInput> {
  await validateGapOwnership(view, review, completion)
  if (!completion.report || completion.report.schema !== 'nasus.image-build-completion.v2'
      || await canonicalDigest(completion.report) !== completion.command.result?.build_completion?.report_hash) {
    throw new Error('An unchanged original v2 completion assessment is required')
  }
  const selected = pin ?? { completion_invocation_id: completion.command.id, completion_report_hash: view.completion_report_hash,
    revision_id: view.revision_id!, revision_hash: view.revision_hash! }
  selectedRevision(view, completion, selected)
  return { ...completionInput(review), ownership_pin: selected }
}

async function validateCommand(command: BuildCompletionCommand, review: BuildReviewHandoff,
  pointer: BuildCompletionPointer, input: OwnedBuildCompletionInput) {
  if (!command || !validReviewId(command.id) || pointer.invocationId !== null && command.id !== pointer.invocationId
      || command.tool_id !== toolId || command.conversation_id !== review.goal.conversation_id
      || command.input_payload?.idempotency_key !== pointer.requestKey
      || !['pending', 'running', 'completed', 'failed', 'cancelled'].includes(command.status)
      || !await equal(Object.fromEntries(Object.entries(command.input_payload).filter(([key]) => key !== 'idempotency_key')), input)
      || command.result && (command.result.invocation_id !== command.id || command.result.status !== command.status)) {
    throw new Error('Responsibility-pinned completion differs from its original command')
  }
  if (command.status === 'completed') {
    const receipt = command.result?.build_completion
    if (receipt?.kind !== 'build_completion' || receipt.project_id !== input.project_id
        || receipt.investigation_revision_id !== input.investigation_revision_id
        || receipt.investigation_revision_hash !== input.investigation_revision_hash
        || receipt.request_hash !== await canonicalDigest(input) || !validReviewHash(receipt.report_hash)
        || !await equal(command.result?.object_refs, [`build_completion:${command.id}`])) {
      throw new Error('Responsibility-pinned completion receipt failed verification')
    }
  }
  return command
}

export async function deriveOwnedCompletionReport(completion: BuildCompletionObservation,
  view: GapOwnershipView, pin: CompletionOwnershipPin): Promise<OwnedBuildCompletionReport> {
  const original = completion.report!
  const revision = selectedRevision(view, completion, pin)
  const gaps = await Promise.all(original.gaps.filter((gap) => gap.code !== 'gap_ownership_unassigned').map(async (gap) => {
    const gapId = 'gap_' + (await canonicalDigest({ code: gap.code, blocks: gap.blocks,
      reason: gap.reason, required_action: gap.required_action })).slice(7)
    const assignment = revision.assignments.find((item) => item.gap_id === gapId)
    if (!assignment) throw new Error('Responsibility revision omits an original gap')
    return { ...gap, gap_id: gapId, owner_actor_id: assignment.owner_actor_id,
      ownership_status: 'confirmed', resolution_status: 'unresolved' as const }
  }))
  return { ...original, schema: 'nasus.image-build-completion.v3',
    ownership: { ...pin, assignment_count: revision.assignments.length, basis: 'confirmed_revision_not_gap_resolution' },
    gaps, blockers: original.blockers.filter((code) => code !== 'gap_ownership_unassigned') }
}

export const ownedBuildCompletionApi = {
  async prepare(review: BuildReviewHandoff, completion: BuildCompletionObservation, view: GapOwnershipView,
    pointer: BuildCompletionPointer) {
    if (!validReviewId(pointer.requestKey) || pointer.invocationId !== null) throw new Error('A fresh request key is required')
    const signal = new AbortController().signal
    const current = await buildGapOwnershipApi.read(review, completion, signal)
    if (view.revision_id !== current.revision_id || view.revision_hash !== current.revision_hash
        || current.gaps.some((gap) => gap.ownership_status !== 'confirmed')) throw new Error('Responsibility selection changed or an owner is unavailable')
    const input = await ownedCompletionInput(review, completion, current)
    const goal = await request(`/v1/agent-goals/${encodeURIComponent(review.goal.id)}`, { signal, cache: 'no-store' })
    if (!await equal(goal, review.goal)) throw new Error('Build checkpoint changed before assessment')
    const command = await platformApi.invokeTool({ tool_id: toolId, conversation_id: review.goal.conversation_id,
      idempotency_key: pointer.requestKey, input: { ...input } })
    return validateCommand(command, review, pointer, input)
  },
  async read(review: BuildReviewHandoff, completion: BuildCompletionObservation, pointer: BuildCompletionPointer,
    signal: AbortSignal): Promise<OwnedBuildCompletionObservation> {
    signal.throwIfAborted()
    let id = pointer.invocationId
    if (id === null) {
      const params = new URLSearchParams({ conversation_id: review.goal.conversation_id, tool_id: toolId })
      const commands = await request<BuildCompletionCommand[]>(`/v1/tool-invocations?${params}`, { signal, cache: 'no-store' })
      if (!Array.isArray(commands) || commands.length > 256) throw new Error('Owned completion discovery exceeds its complete bound')
      const matches = commands.filter((item) => item.input_payload?.idempotency_key === pointer.requestKey)
      if (matches.length !== 1) throw new Error('The original owned completion command could not be uniquely found')
      id = matches[0].id
    }
    const raw = await platformApi.getToolInvocation(id, { signal })
    const view = await buildGapOwnershipApi.read(review, completion, signal)
    if (!raw.input_payload?.ownership_pin) throw new Error('The original command has no explicit responsibility pin')
    const input = await ownedCompletionInput(review, completion, view, raw.input_payload.ownership_pin as CompletionOwnershipPin)
    const command = await validateCommand(raw, review, { ...pointer, invocationId: id }, input)
    let report: OwnedBuildCompletionReport | null = null
    if (command.status === 'completed') {
      report = await request<OwnedBuildCompletionReport>(
        `/v1/projects/${encodeURIComponent(review.projectId)}/system-image/build-completions/${encodeURIComponent(id)}`,
        { signal, cache: 'no-store' })
      if (await canonicalDigest(report) !== command.result?.build_completion?.report_hash
          || !await equal(report, await deriveOwnedCompletionReport(completion, view, input.ownership_pin))) {
        throw new Error('Owned completion changed original facts, owners, readiness or unresolved blockers')
      }
    }
    const goal = await request(`/v1/agent-goals/${encodeURIComponent(review.goal.id)}`, { signal, cache: 'no-store' })
    signal.throwIfAborted()
    if (!await equal(goal, review.goal)) throw new Error('Build checkpoint changed during assessment replay')
    return { command, report }
  },
}
