import { request } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import { validReviewHash, validReviewId, type BuildReviewHandoff } from './buildReviewHandoff'
import type { BuildCompletionObservation, BuildCompletionPointer } from './types/buildCompletion'
import type { GapAssignment, GapOwnerOption, GapOwnershipCommand, GapOwnershipInput, GapOwnershipObservation, GapOwnershipView } from './types/buildGapOwnership'

export const gapOwnershipTool = 'system_image.build.gaps.assign'
const equal = async (a: unknown, b: unknown) => await canonicalDigest(a) === await canonicalDigest(b)
const basePath = (review: BuildReviewHandoff, completion: BuildCompletionObservation) =>
  `/v1/projects/${encodeURIComponent(review.projectId)}/system-image/build-completions/${encodeURIComponent(completion.command.id)}`
const coordination = new Set(['idempotency_key', 'confirmed_at', 'confirmed_actor_id', 'confirmed_by_user'])

export function parseGapAssignmentPointer(params: URLSearchParams): BuildCompletionPointer | null {
  const keys = params.getAll('build_gap_assignment_request'), ids = params.getAll('build_gap_assignment_invocation')
  if (!keys.length && !ids.length) return null
  if (keys.length !== 1 || ids.length > 1 || !validReviewId(keys[0]) || ids.length && !validReviewId(ids[0])) {
    throw new Error('Invalid gap responsibility pointer')
  }
  return { requestKey: keys[0], invocationId: ids[0] ?? null }
}

export function assignmentInput(review: BuildReviewHandoff, completion: BuildCompletionObservation,
  view: Pick<GapOwnershipView, 'revision_id' | 'revision_hash'>, assignments: GapAssignment[]): GapOwnershipInput {
  const receipt = completion.command.result?.build_completion
  if (!completion.report || !receipt) throw new Error('A verified original completion report is required')
  return { project_id: review.projectId, completion_invocation_id: completion.command.id,
    completion_report_hash: receipt.report_hash, expected_goal: review.goal,
    parent_revision_id: view.revision_id, parent_revision_hash: view.revision_hash, assignments }
}

function validateAssignments(assignments: GapAssignment[], gapIds: string[]) {
  if (!Array.isArray(assignments) || assignments.length !== gapIds.length
      || new Set(assignments.map((item) => item.gap_id)).size !== gapIds.length
      || assignments.some((item) => !gapIds.includes(item.gap_id) || !validReviewId(item.owner_actor_id)
        || typeof item.reason !== 'string' || !item.reason.trim() || item.reason.length > 1000
        || Object.keys(item).sort().join(',') !== 'gap_id,owner_actor_id,reason')) throw new Error('Incomplete gap responsibility inventory')
}

export async function validateGapOwnership(view: GapOwnershipView, review: BuildReviewHandoff,
  completion: BuildCompletionObservation): Promise<GapOwnershipView> {
  if (!completion.report || view?.schema !== 'nasus.image-build-gap-ownership.v1' || view.project_id !== review.projectId
      || view.completion_invocation_id !== completion.command.id
      || view.completion_report_hash !== completion.command.result?.build_completion?.report_hash
      || view.is_current_revision !== true || view.goal_completed !== false || view.execution_authorized !== false
      || view.publication_authorized !== false || !Array.isArray(view.history) || view.history.length > 80
      || !Array.isArray(view.gaps) || !view.gaps.length || view.gaps.length > 96) throw new Error('Invalid gap responsibility scope')
  const definitions = new Map<string, { code: string; blocks: string; reason: string; required_action: string }>()
  for (const gap of completion.report.gaps.filter((item) => item.code !== 'gap_ownership_unassigned')) {
    const definition = { code: gap.code, blocks: gap.blocks, reason: gap.reason, required_action: gap.required_action }
    definitions.set('gap_' + (await canonicalDigest(definition)).slice(7), definition)
  }
  const ids = Array.from(definitions.keys()).sort()
  if (!await equal(view.gaps.map((gap) => gap.gap_id), ids)) throw new Error('Gap definitions differ from the original report')
  let previous: typeof view.history[number] | null = null
  const revisionIds = new Set<string>(), invocationIds = new Set<string>()
  for (const [index, revision] of view.history.entries()) {
    validateAssignments(revision.assignments, ids)
    const input = assignmentInput(review, completion, { revision_id: previous?.revision_id ?? null,
      revision_hash: previous?.revision_hash ?? null }, revision.assignments)
    const digest = await canonicalDigest({ schema: view.schema, request: input, revision_number: index + 1,
      confirmed_by: revision.confirmed_by, created_at: revision.created_at })
    if (!validReviewId(revision.revision_id) || revisionIds.has(revision.revision_id)
        || !validReviewId(revision.invocation_id) || invocationIds.has(revision.invocation_id)
        || !validReviewId(revision.confirmed_by) || !Number.isFinite(Date.parse(revision.created_at))
        || revision.revision_number !== index + 1 || revision.revision_hash !== digest) throw new Error('Gap responsibility history failed replay verification')
    revisionIds.add(revision.revision_id); invocationIds.add(revision.invocation_id); previous = revision
  }
  if (view.revision_number !== view.history.length || view.revision_id !== (previous?.revision_id ?? null)
      || view.revision_hash !== (previous?.revision_hash ?? null)) throw new Error('Gap responsibility predecessor is incomplete')
  for (const gap of view.gaps) {
    const assignment = previous?.assignments.find((item) => item.gap_id === gap.gap_id)
    const definition = { code: gap.code, blocks: gap.blocks, reason: gap.reason, required_action: gap.required_action }
    if (!await equal(definition, definitions.get(gap.gap_id)) || gap.resolution_status !== 'unresolved'
        || gap.owner_actor_id !== (assignment?.owner_actor_id ?? null)
        || !(assignment ? ['confirmed', 'owner_unavailable'] : ['unassigned']).includes(gap.ownership_status)) {
      throw new Error('Gap responsibility must not resolve or rewrite its original gap')
    }
  }
  return view
}

async function validateCommand(command: GapOwnershipCommand, review: BuildReviewHandoff,
  completion: BuildCompletionObservation, pointer: BuildCompletionPointer, view: GapOwnershipView) {
  const id = pointer.invocationId
  const body = Object.fromEntries(Object.entries(command.input_payload ?? {}).filter(([key]) => !coordination.has(key))) as unknown as GapOwnershipInput
  validateAssignments(body.assignments, view.gaps.map((gap) => gap.gap_id))
  if (command.id !== id || !validReviewId(id) || command.tool_id !== gapOwnershipTool
      || command.conversation_id !== review.goal.conversation_id || command.input_payload.idempotency_key !== pointer.requestKey
      || !['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(command.status)
      || !await equal(body, assignmentInput(review, completion, { revision_id: body.parent_revision_id,
        revision_hash: body.parent_revision_hash }, body.assignments))
      || (body.parent_revision_id === null) !== (body.parent_revision_hash === null)
      || body.parent_revision_id !== null && (!validReviewId(body.parent_revision_id) || !validReviewHash(body.parent_revision_hash))) {
    throw new Error('Gap responsibility command differs from the original fixed review')
  }
  if (command.status === 'completed') {
    const receipt = command.result?.build_gap_ownership
    const saved = view.history.find((item) => item.invocation_id === id)
    const predecessor = saved ? view.history[view.history.indexOf(saved) - 1] : null
    if (!receipt || !saved || receipt.kind !== 'build_gap_ownership' || receipt.project_id !== review.projectId
        || receipt.completion_invocation_id !== completion.command.id || receipt.completion_report_hash !== view.completion_report_hash
        || receipt.revision_id !== saved.revision_id || receipt.revision_hash !== saved.revision_hash
        || body.parent_revision_id !== (predecessor?.revision_id ?? null)
        || body.parent_revision_hash !== (predecessor?.revision_hash ?? null)
        || !await equal(body.assignments, saved.assignments)) throw new Error('Gap responsibility receipt failed verification')
  }
  return command
}

async function readCommand(review: BuildReviewHandoff, completion: BuildCompletionObservation,
  pointer: BuildCompletionPointer, signal: AbortSignal, view: GapOwnershipView) {
  let id = pointer.invocationId
  if (id === null) {
    const params = new URLSearchParams({ conversation_id: review.goal.conversation_id, tool_id: gapOwnershipTool })
    const commands = await request<GapOwnershipCommand[]>(`/v1/tool-invocations?${params}`, { signal, cache: 'no-store' })
    if (!Array.isArray(commands) || commands.length > 256) throw new Error('Gap command discovery exceeded its complete bound')
    const matches = commands.filter((item) => item.input_payload?.idempotency_key === pointer.requestKey)
    if (matches.length !== 1) throw new Error('Original gap responsibility command could not be found')
    id = matches[0].id
  }
  const command = await platformApi.getToolInvocation(id, { signal }) as GapOwnershipCommand
  return validateCommand(command, review, completion, { ...pointer, invocationId: id }, view)
}

export const buildGapOwnershipApi = {
  async read(review: BuildReviewHandoff, completion: BuildCompletionObservation, signal: AbortSignal) {
    return validateGapOwnership(await request<GapOwnershipView>(`${basePath(review, completion)}/gap-ownership`,
      { signal, cache: 'no-store' }), review, completion)
  },
  async owners(review: BuildReviewHandoff, completion: BuildCompletionObservation, signal: AbortSignal) {
    const options = await request<GapOwnerOption[]>(`${basePath(review, completion)}/gap-owners`, { signal, cache: 'no-store' })
    if (!Array.isArray(options) || options.length > 200 || new Set(options.map((item) => item.actor_id)).size !== options.length
        || options.some((item) => !validReviewId(item.actor_id) || typeof item.display_name !== 'string')) throw new Error('Invalid owner selection')
    return options
  },
  async command(review: BuildReviewHandoff, completion: BuildCompletionObservation,
    pointer: BuildCompletionPointer, signal: AbortSignal): Promise<GapOwnershipCommand> {
    const view = await this.read(review, completion, signal)
    return readCommand(review, completion, pointer, signal, view)
  },
  async observe(review: BuildReviewHandoff, completion: BuildCompletionObservation,
    pointer: BuildCompletionPointer | null, signal: AbortSignal): Promise<GapOwnershipObservation> {
    const view = await this.read(review, completion, signal)
    return { view, command: pointer ? await readCommand(review, completion, pointer, signal, view) : null }
  },
  async prepare(review: BuildReviewHandoff, completion: BuildCompletionObservation, input: GapOwnershipInput,
    pointer: BuildCompletionPointer) {
    if (!validReviewId(pointer.requestKey) || pointer.invocationId !== null) throw new Error('A new assignment requires a fresh request pointer')
    const signal = new AbortController().signal
    const current = await this.read(review, completion, signal)
    if (!await equal(input, assignmentInput(review, completion, current, input.assignments))) throw new Error('Gap responsibility predecessor changed')
    validateAssignments(input.assignments, current.gaps.map((gap) => gap.gap_id))
    const command = await platformApi.invokeTool({ tool_id: gapOwnershipTool, conversation_id: review.goal.conversation_id,
      idempotency_key: pointer.requestKey, input: { ...input } })
    // A fresh prepare response is already source-authorized. Only a replayed
    // completed command needs its newly persisted history read back.
    const view = command.status === 'completed' ? await this.read(review, completion, signal) : current
    return { view, command: await validateCommand(command, review, completion, { ...pointer, invocationId: command.id }, view) }
  },
  async confirm(review: BuildReviewHandoff, completion: BuildCompletionObservation, pointer: BuildCompletionPointer) {
    const signal = new AbortController().signal
    const observation = await this.observe(review, completion, pointer, signal)
    const command = observation.command!, current = observation.view
    const goal = await request(`/v1/agent-goals/${encodeURIComponent(review.goal.id)}`, { signal, cache: 'no-store' })
    if (command.status !== 'waiting_confirmation' || !await equal(goal, review.goal)
        || command.input_payload.parent_revision_id !== current.revision_id
        || command.input_payload.parent_revision_hash !== current.revision_hash) throw new Error('Gap confirmation changed; reread before preparing another command')
    const confirmed = await platformApi.confirmToolInvocation(command.id)
    const view = await this.read(review, completion, signal)
    return { view, command: await validateCommand(confirmed, review, completion, { ...pointer, invocationId: command.id }, view) }
  },
}
