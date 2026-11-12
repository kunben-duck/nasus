import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { deliveryHash, deliveryId } from './iterationCreation'

export type ClarificationAnswer = { question: string; answer: string }
export type RequirementInput = {
  project_id: string; version_id: string; image_revision_id: string; image_artifact_hash: string
  us_id?: string; expected_revision_id?: string; title: string; text: string
  clarification_answers: ClarificationAnswer[]
}
export type RequirementRevision = Omit<RequirementInput, 'us_id' | 'expected_revision_id'> & {
  us_id: string; revision_id: string; sequence: number; previous_revision_id: string | null
  original_text: string; recorded_at: string; actor_id: string; invocation_id: string
  content_hash: string; status: 'draft'; generation_authorized: false
}
export type RequirementPage = {
  project_id: string; version_id: string; items: RequirementRevision[]; next_offset: number | null; blockers: string[]
}
export type RequirementAttempt = { actor_id: string; key: string; input: RequirementInput }

export function verifyRequirementInput(input: RequirementInput) {
  if (!deliveryId(input.project_id) || !deliveryId(input.version_id) || !deliveryId(input.image_revision_id)
      || !deliveryHash(input.image_artifact_hash) || !input.title?.trim() || input.title.length > 200
      || !input.text?.trim() || input.text.length > 16000 || !!input.us_id !== !!input.expected_revision_id
      || (input.us_id && (!deliveryId(input.us_id) || !deliveryId(input.expected_revision_id)))
      || !Array.isArray(input.clarification_answers) || input.clarification_answers.length > 32
      || input.clarification_answers.some((item) => typeof item.question !== 'string' || !item.question.trim()
        || item.question.length > 2000 || typeof item.answer !== 'string' || !item.answer.trim() || item.answer.length > 4000)
      || new Set(input.clarification_answers.map((item) => item.question.trim())).size !== input.clarification_answers.length) {
    throw new Error('Requirement input is incomplete or inconsistent')
  }
  return input
}

export function verifyRequirementPage(value: RequirementPage, projectId: string, versionId: string) {
  if (value.project_id !== projectId || value.version_id !== versionId || !Array.isArray(value.items)
      || !Array.isArray(value.blockers) || value.blockers.some((item) => typeof item !== 'string')
      || (value.next_offset !== null && (!Number.isInteger(value.next_offset) || value.next_offset < 1))) {
    throw new Error('Requirement scope mismatch')
  }
  for (const item of value.items) {
    if (item.project_id !== projectId || item.version_id !== versionId || !deliveryId(item.us_id)
        || !deliveryId(item.revision_id) || !deliveryHash(item.content_hash) || item.status !== 'draft'
        || item.generation_authorized !== false || typeof item.original_text !== 'string'
        || !Number.isInteger(item.sequence) || item.sequence < 1) throw new Error('Requirement revision mismatch')
    verifyRequirementInput({ ...item, us_id: undefined, expected_revision_id: undefined })
  }
  if (new Set(value.items.map((item) => item.revision_id)).size !== value.items.length) throw new Error('Duplicate requirement revision')
  return value
}

export const requirementAttemptKey = (actor: string, project: string, version: string) =>
  `nasus.requirement-intake:${JSON.stringify([actor, project, version])}`

export function restoreRequirementAttempt(raw: string | null, actor: string, project: string, version: string) {
  if (!raw) return null
  const attempt = JSON.parse(raw) as RequirementAttempt
  if (attempt.actor_id !== actor || attempt.input?.project_id !== project || attempt.input?.version_id !== version
      || !deliveryId(attempt.key)) throw new Error('Requirement recovery scope mismatch')
  verifyRequirementInput(attempt.input)
  return attempt
}

export const requirementRevisionsApi = {
  async list(projectId: string, versionId: string, signal: AbortSignal, usId?: string, offset = 0) {
    const params = new URLSearchParams({ offset: String(offset) })
    if (usId) params.set('us_id', usId)
    const value = await request<RequirementPage>(`/v1/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/requirements?${params}`,
      { signal, cache: 'no-store' })
    signal.throwIfAborted()
    return verifyRequirementPage(value, projectId, versionId)
  },
  async save(attempt: RequirementAttempt) {
    const input = verifyRequirementInput(attempt.input)
    const result = await platformApi.invokeTool({ tool_id: 'quality.requirement.revise', input: { ...input }, idempotency_key: attempt.key })
    const stored = result.input_payload
    if (result.tool_id !== 'quality.requirement.revise' || !stored || result.result?.invocation_id !== result.id
        || ['project_id', 'version_id', 'title', 'text', 'image_revision_id', 'image_artifact_hash', 'us_id', 'expected_revision_id']
          .some((key) => (stored[key] ?? null) !== (input[key as keyof RequirementInput] ?? null))
        || JSON.stringify(stored.clarification_answers) !== JSON.stringify(input.clarification_answers)) throw new Error('Requirement command mismatch')
    return result
  },
}
