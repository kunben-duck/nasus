import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest } from './testDesignGenerationValidation'
import { requireScopeDraft } from './scopeDraftValidation'
import type { ToolInvocation } from '../platform/types'
import type { ScopeDraftRequest } from './scopeDraftApi'

export interface ScopeDraftAttempt {
  projectId: string; contextId: string; contextHash: string; requestKey: string; requestHash: string; commandId?: string
}
type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
const id = (value: unknown) => typeof value === 'string' && !!value && value.length <= 128
export function verifyScopeDraftAttempt(value: unknown): ScopeDraftAttempt {
  const v = value as ScopeDraftAttempt
  requireScopeDraft(v && [v.projectId, v.contextId, v.requestKey].every(id) && generationDigest(v.contextHash)
    && generationDigest(v.requestHash) && (v.commandId === undefined || id(v.commandId))
    && Object.keys(v).every((key) => ['projectId', 'contextId', 'contextHash', 'requestKey', 'requestHash', 'commandId'].includes(key)))
  return v
}
export function createScopeDraftRecovery(storage: () => StoragePort) {
  const key = (actor: string, value: Pick<ScopeDraftAttempt, 'projectId' | 'contextId' | 'contextHash'>) => {
    requireScopeDraft(id(actor) && id(value.projectId) && id(value.contextId) && generationDigest(value.contextHash))
    return 'nasus.scope-draft.v1:' + JSON.stringify([actor, value.projectId, value.contextId, value.contextHash])
  }
  const read = (actor: string, scope: Pick<ScopeDraftAttempt, 'projectId' | 'contextId' | 'contextHash'>) => {
    const raw = storage().getItem(key(actor, scope))
    if (raw === null) return null
    requireScopeDraft(raw.length <= 2048)
    const v = verifyScopeDraftAttempt(JSON.parse(raw))
    requireScopeDraft(v.projectId === scope.projectId && v.contextId === scope.contextId && v.contextHash === scope.contextHash)
    return v
  }
  const write = (actor: string, value: ScopeDraftAttempt) => {
    verifyScopeDraftAttempt(value)
    const name = key(actor, value), raw = JSON.stringify(value)
    storage().setItem(name, raw); requireScopeDraft(storage().getItem(name) === raw)
  }
  return { read,
    save(actor: string, value: ScopeDraftAttempt) {
      requireScopeDraft(!read(actor, value) && !value.commandId); write(actor, value)
    },
    acknowledge(actor: string, value: ScopeDraftAttempt) {
      const old = read(actor, value)
      requireScopeDraft(old && old.requestKey === value.requestKey && old.requestHash === value.requestHash && id(value.commandId)
        && (!old.commandId || old.commandId === value.commandId)); write(actor, value)
    },
    clear(actor: string, value: ScopeDraftAttempt) {
      const old = read(actor, value)
      requireScopeDraft(old && old.requestKey === value.requestKey && old.requestHash === value.requestHash && old.commandId === value.commandId)
      const name = key(actor, value); storage().removeItem(name); requireScopeDraft(storage().getItem(name) === null)
    },
  }
}
export const scopeDraftRecovery = createScopeDraftRecovery(() => window.localStorage)
const requestKeys = ['project_id', 'context_id', 'context_artifact_hash', 'model_config_id', 'budget', 'input_digest', 'model_config_digest', 'plan_digest'] as const
export async function verifyScopeDraftCommand(command: ToolInvocation, attempt: ScopeDraftAttempt) {
  verifyScopeDraftAttempt(attempt)
  const body = command?.input_payload, input = Object.fromEntries(requestKeys.map((key) => [key, body?.[key]])) as unknown as ScopeDraftRequest
  requireScopeDraft(command && id(command.id) && (!attempt.commandId || attempt.commandId === command.id)
    && command.tool_id === 'quality.test_design_scope.draft' && body?.idempotency_key === attempt.requestKey
    && input.project_id === attempt.projectId && input.context_id === attempt.contextId && input.context_artifact_hash === attempt.contextHash
    && await canonicalDigest(input) === attempt.requestHash
    && ['pending', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled'].includes(command.status))
  if (command.status === 'completed') requireScopeDraft(body.confirmed_by_user === true && command.result?.status === 'completed'
    && command.result.invocation_id === command.id && command.result.object_refs.includes(`scope_draft:${command.id}`))
  return { command, input, attempt: { ...attempt, commandId: command.id } }
}
