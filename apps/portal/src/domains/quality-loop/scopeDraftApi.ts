import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ContextArchive } from '../system-image/types/contextPack'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { scopeContractValid } from './testDesignScopeDraft'
import type { TestDesignContract } from './types/testDesignScope'
import type { GenerationBudget, GenerationPreview } from './types/testDesignGeneration'
import type { ToolInvocation } from '../platform/types'
import { requireScopeDraft as requireDraft, verifyScopeDraftPreview } from './scopeDraftValidation'
import { verifyScopeDraftCommand, type ScopeDraftAttempt } from './scopeDraftRecovery'

export interface ScopeDraftSelection {
  project_id: string; context_id: string; context_artifact_hash: string; model_config_id: string; budget: GenerationBudget
}
export interface ScopeDraftRequest extends ScopeDraftSelection { input_digest: string; model_config_digest: string; plan_digest: string }
export interface ScopeDraftPreview {
  request: ScopeDraftRequest; provider: string; model_name: string; destination: string
  review_required: true; generation_authorized: false
  plan: { source_binding_ids: string[]; source_scope_digest: string; messages_hash: string; input_digest: string
    model_binding: { config_id: string; config_digest: string; provider: string; model_name: string; base_url: string }
    budget: GenerationBudget; policy: GenerationPreview['policy']; reservation: GenerationPreview['reservation']; timeout_seconds: 120 }
}
export interface ScopeDraftItem {
  invocation_id: string; actor_id: string; recorded_at: string
  status: 'reserved' | 'reply_archived' | 'failed' | 'draft'; provider_outcome_unknown: boolean
}
export interface ScopeModelDraft {
  invocation_id: string; actor_id: string; context_id: string; context_artifact_hash: string; artifact_hash: string
  contract: Omit<TestDesignContract, 'authority_basis'> & { authority_basis: 'model_suggestion' }
  status: 'draft'; review_required: true; generation_authorized: false; execution_authorized: false
  current_use: { context_current: boolean; generation_authorized: false }
}
const root = (project: string) => `/v1/projects/${encodeURIComponent(project)}/quality/scope-drafts`
export function scopeDraftForReview(value: ScopeModelDraft, context: ContextArchive): TestDesignContract {
  requireDraft(value?.status === 'draft' && value.review_required === true && value.generation_authorized === false
    && value.execution_authorized === false && value.context_id === context.metadata.context_id
    && value.context_artifact_hash === context.metadata.artifact_hash && generationDigest(value.artifact_hash)
    && value.contract?.authority_basis === 'model_suggestion' && value.current_use?.generation_authorized === false)
  const contract: TestDesignContract = { ...value.contract, authority_basis: 'user_confirmed_test_design_scope' }
  requireDraft(scopeContractValid(contract, context.context) && contract.examples.every((example) =>
    generationEqual(example.positive, context.context.required_constraints.find((row) => row.object_id === example.constraint_id)?.oracle)))
  return contract
}
export const scopeDraftApi = {
  async preview(selection: ScopeDraftSelection) {
    const value = await request<ScopeDraftPreview>(`${root(selection.project_id)}/preview`, {
      method: 'POST', body: JSON.stringify(selection), cache: 'no-store' })
    return verifyScopeDraftPreview(value, selection)
  },
  async generate(input: ScopeDraftRequest, attempt: ScopeDraftAttempt, acknowledge: (attempt: ScopeDraftAttempt) => void) {
    const pending = await verifyScopeDraftCommand(await platformApi.invokeTool({ tool_id: 'quality.test_design_scope.draft',
      input: { ...input }, idempotency_key: attempt.requestKey }), attempt)
    requireDraft(pending.command.status === 'waiting_confirmation')
    acknowledge(pending.attempt)
    return this.confirmOriginal(pending.attempt)
  },
  async recover(attempt: ScopeDraftAttempt, signal: AbortSignal) {
    const command = attempt.commandId ? await platformApi.getToolInvocation(attempt.commandId, { signal })
      : await request<ToolInvocation>(`/v1/tool-invocations/resolve?${new URLSearchParams({ project_id: attempt.projectId,
        tool_id: 'quality.test_design_scope.draft', request_key: attempt.requestKey })}`, { signal, cache: 'no-store' })
    signal.throwIfAborted()
    return verifyScopeDraftCommand(command, attempt)
  },
  async confirmOriginal(attempt: ScopeDraftAttempt) {
    requireDraft(attempt.commandId)
    return verifyScopeDraftCommand(await platformApi.confirmToolInvocation(attempt.commandId), attempt)
  },
  async history(context: ContextArchive, signal: AbortSignal) {
    const value = await request<{ items: ScopeDraftItem[] }>(`${root(context.metadata.project_id)}?${new URLSearchParams({ context_id: context.metadata.context_id })}`, { signal, cache: 'no-store' })
    requireDraft(Array.isArray(value?.items) && value.items.length <= 100 && value.items.every((item) =>
      typeof item.invocation_id === 'string' && !!item.invocation_id && typeof item.actor_id === 'string'
      && ['reserved', 'reply_archived', 'failed', 'draft'].includes(item.status) && typeof item.provider_outcome_unknown === 'boolean'))
    return value.items
  },
  async read(context: ContextArchive, id: string, signal: AbortSignal) {
    const value = await request<ScopeModelDraft>(`${root(context.metadata.project_id)}/${encodeURIComponent(id)}`, { signal, cache: 'no-store' })
    requireDraft(value.invocation_id === id)
    scopeDraftForReview(value, context)
    return value
  },
}
