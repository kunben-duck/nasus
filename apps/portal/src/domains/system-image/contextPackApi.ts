import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { oracleKeys } from '../quality-loop/acceptanceSpecificationApi'
import type { ContextArchive, ContextHistory, ContextMetadata, ContextPreview, ContextRequest, ContextSelection, TestDesignContext } from './types/contextPack'
import { verifyPartitions } from './contextPartitionContract'

const root = (project: string) => `/v1/projects/${encodeURIComponent(project)}/system-image/context-packs`
const digest = (value: string) => /^sha256:[0-9a-f]{64}$/.test(value)
const sameScope = (a: ContextSelection, b: ContextSelection) => a.project_id === b.project_id && a.image_revision_id === b.image_revision_id && a.image_artifact_hash === b.image_artifact_hash
const bindingsKey = (value: ContextRequest) => value.retrieval_bindings === undefined ? undefined : JSON.stringify(Object.entries(value.retrieval_bindings).sort(([a], [b]) => a.localeCompare(b)))
const sameRequest = (a: ContextRequest, b: ContextRequest) => sameScope(a, b) && a.purpose === b.purpose && a.policy_revision === b.policy_revision && a.max_tokens === b.max_tokens && a.candidate_limit === b.candidate_limit && a.publication_id === b.publication_id && bindingsKey(a) === bindingsKey(b)
export class StaleContextPreview extends Error {}

function verifyContext(context: TestDesignContext, selection: ContextRequest, child = false) {
  const indexed = selection.policy_revision === 'nasus.test-design-context.v5'
  const partitioned = ['nasus.test-design-context.v2', 'nasus.test-design-context.v3', 'nasus.test-design-context.v4', 'nasus.test-design-context.v5'].includes(selection.policy_revision)
  const expectedSchema = partitioned && !child ? 'nasus.context-bundle.v1' : 'nasus.context-pack.v1'
  if (!sameScope(context, selection) || context.schema_version !== expectedSchema || context.purpose !== 'test_design'
      || context.policy_version !== selection.policy_revision || !context.source_manifest_id || !digest(context.source_manifest_hash)
      || context.use_policy !== 'draft_investigation_only_not_generation_or_execution_authorization'
      || context.retrieval.method !== (indexed ? 'nasus.link-recall.indexed-reviewed.v3' : 'nasus.link-recall.reviewed.v2')
      || typeof context.retrieval.truncated !== 'boolean' || typeof context.retrieval.fallback_used !== 'boolean'
      || !indexed && context.retrieval.fallback_used !== true
      || context.conflicts.status !== 'not_evaluated' || !['partial', 'blocked'].includes(context.readiness.status)
      || !context.readiness.reason_codes.length || context.budget.measure !== 'utf8_bytes_upper_bound_not_provider_token_count'
      || context.budget.max_tokens !== selection.max_tokens || context.budget.used_upper_bound > selection.max_tokens
      || !Number.isSafeInteger(context.budget.used_upper_bound) || context.budget.used_upper_bound < 1
      || !Number.isSafeInteger(context.budget.omitted_optional_facts) || context.budget.omitted_optional_facts < 0
      || context.required_constraints.length > (partitioned ? 256 : 32) || new Set(context.required_constraints.map((c) => c.object_id)).size !== context.required_constraints.length
      || (child || !partitioned) && (context.parts !== undefined || context.budget.scope !== undefined)
      || !child && context.partition !== undefined) {
    throw new Error('Context contract mismatch')
  }
  const pin = context.publication_pin
  if (selection.policy_revision === 'nasus.test-design-context.v4' || indexed) {
    if (!selection.publication_id || !pin || pin.publication_id !== selection.publication_id
        || pin.image_revision_id !== selection.image_revision_id || pin.image_artifact_hash !== selection.image_artifact_hash
        || pin.manifest_id !== context.source_manifest_id || pin.manifest_hash !== context.source_manifest_hash
        || !pin.baseline_id || !Number.isSafeInteger(pin.sequence) || pin.sequence < 1
        || pin.quality_generation_authorized !== false || pin.release_authorized !== false
        || context.readiness.reason_codes.includes('image_not_published')) throw new Error('Context publication mismatch')
  } else if (pin !== undefined || selection.publication_id !== undefined) throw new Error('Legacy context cannot claim publication')
  if (indexed) {
    const bindings = selection.retrieval_bindings
    const targets = context.required_constraints.filter((c) => c.kind === 'acceptance_criterion').map((c) => c.object_id)
    if (!bindings || Array.isArray(bindings) || Object.keys(bindings).length > 256
        || Object.entries(bindings).some(([key, value]) => !key || key.length > 128 || typeof value !== 'string' || !value || value.length > 128)
        || targets.some((id) => !Object.hasOwn(bindings, id)) || !child && Object.keys(bindings).length !== targets.length
        || !context.readiness.reason_codes.includes('bounded_saved_trace_recall')) throw new Error('Context retrieval bindings mismatch')
  } else if (selection.retrieval_bindings !== undefined) throw new Error('Legacy context cannot claim indexed recall')
  for (const c of context.required_constraints) {
    if (!c.object_id || !c.source_revision_id || !c.document_revision_id || !c.evidence_ids.length || !c.source_fields.length
        || partitioned && !['acceptance_criterion', 'business_rule'].includes(c.kind ?? '')
        || c.authority.object_id !== c.object_id || !['approved', 'withdrawn', 'unapproved'].includes(c.authority.status)
        || c.source_fields.some((f) => !f.value.trim() || !digest(f.snippet_hash) || f.start_line < 1 || f.end_line < f.start_line)) throw new Error('Context requirement mismatch')
    if (c.authority.status === 'approved') {
      if (!c.authority.revision_id || !digest(c.authority.artifact_hash!) || c.semantic_class !== 'expected' || !c.oracle
          || oracleKeys.some((field) => !c.oracle![field]?.trim())) throw new Error('Context oracle mismatch')
    } else if (c.oracle !== null || c.semantic_class !== 'pending_confirmation') throw new Error('Unapproved context oracle')
  }
  const blocked = !context.required_constraints.length || context.required_constraints.some((c) => c.oracle === null)
  if (context.readiness.status !== (blocked ? 'blocked' : 'partial')) throw new Error('Context readiness mismatch')
  if (context.facts.some((f) => !context.required_constraints.some((c) => c.object_id === f.target_object_id)
      || f.semantic_class !== 'retrieval_candidate_not_coverage' || !['implements', 'asserts'].includes(f.relation)
      || !['unreviewed', 'requires_revalidation', 'reviewed_not_approved'].includes(f.review_status)
      || !f.endpoint.object_id || !f.endpoint.revision_id || !f.endpoint.source_revision_id || !digest(f.endpoint.content_hash) || !f.endpoint.evidence_ids.length)) {
    throw new Error('Context support evidence mismatch')
  }
  if (partitioned && !child) verifyPartitions(context, (part) => verifyContext(part, selection, true))
}
function verifyMetadata(item: ContextMetadata, selection: ContextSelection) {
  if (!sameScope(item, selection) || !item.context_id || !item.invocation_id || !item.actor_id || !item.recorded_at
      || !digest(item.input_digest) || !digest(item.artifact_hash) || !digest(item.content_hash)
      || item.purpose !== 'test_design' || !['nasus.test-design-context.v1', 'nasus.test-design-context.v2', 'nasus.test-design-context.v3', 'nasus.test-design-context.v4', 'nasus.test-design-context.v5'].includes(item.policy_revision)
      || !['partial', 'blocked'].includes(item.readiness) || !Number.isInteger(item.mandatory_count)
      || item.mandatory_count < 0 || item.mandatory_count > (item.policy_revision === 'nasus.test-design-context.v1' ? 32 : 256)) throw new Error('Context metadata mismatch')
}

export const contextPackApi = {
  async preview(selection: ContextRequest, signal: AbortSignal) {
    const params = new URLSearchParams({ image_revision_id: selection.image_revision_id, image_artifact_hash: selection.image_artifact_hash,
      purpose: selection.purpose, policy_revision: selection.policy_revision,
      max_tokens: String(selection.max_tokens), candidate_limit: String(selection.candidate_limit) })
    if (selection.publication_id) params.set('publication_id', selection.publication_id)
    if (selection.retrieval_bindings !== undefined) params.set('retrieval_bindings', JSON.stringify(selection.retrieval_bindings))
    const result = await request<ContextPreview>(`${root(selection.project_id)}/preview?${params}`, { signal, cache: 'no-store' })
    if (!sameRequest(result.request, selection) || !digest(result.input_digest)) throw new Error('Context preview mismatch')
    verifyContext(result.context, selection)
    return result
  },
  async archive(preview: ContextPreview, attempt: string) {
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.context.compile', idempotency_key: attempt,
      input: { ...preview.request, expected_input_digest: preview.input_digest } })
    if (pending.status !== 'waiting_confirmation') throw new Error('Context requires explicit confirmation')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.result?.followup_reason === 'context_inputs_changed') throw new StaleContextPreview('Context inputs changed')
    const refs = done.result?.object_refs.filter((ref) => ref.startsWith('context_pack:')) ?? []
    if (done.status !== 'completed' || refs.length !== 1 || !refs[0].slice(13)) throw new Error('Context archive was not acknowledged')
    return refs[0].slice(13)
  },
  async history(selection: ContextSelection, afterId: string, signal: AbortSignal) {
    const params = new URLSearchParams({ image_revision_id: selection.image_revision_id, image_artifact_hash: selection.image_artifact_hash, after_id: afterId, limit: '10' })
    const page = await request<ContextHistory>(`${root(selection.project_id)}?${params}`, { signal, cache: 'no-store' })
    if (!sameScope(page.request, selection) || page.request.after_id !== afterId || page.request.limit !== 10
        || page.items.length > 10 || new Set(page.items.map((item) => item.context_id)).size !== page.items.length
        || (page.next_after_id !== null && (page.items.length !== 10 || page.next_after_id !== page.items.at(-1)?.context_id))) throw new Error('Context history mismatch')
    page.items.forEach((item) => verifyMetadata(item, selection))
    return page
  },
  async read(selection: ContextSelection, contextId: string, signal: AbortSignal) {
    const value = await request<ContextArchive>(`${root(selection.project_id)}/${encodeURIComponent(contextId)}`, { signal, cache: 'no-store' })
    verifyMetadata(value.metadata, selection)
    if (value.metadata.context_id !== contextId || !sameScope(value.derivation.request, selection)
        || value.derivation.historical_not_live !== true || value.derivation.input_digest !== value.metadata.input_digest
        || value.derivation.request.expected_input_digest !== value.metadata.input_digest || value.current_use.generation_authorized !== false
        || typeof value.current_use.stale !== 'boolean'
        || (value.current_use.stale ? !['inputs_changed', 'current_mandatory_context_over_budget', 'published_image_head_changed', 'retrieval_model_configuration_changed', 'source_change_invalidated'].includes(value.current_use.reason)
          : value.current_use.reason !== 'draft_investigation_only')
        || (value.current_use.reason === 'source_change_invalidated'
          ? typeof value.current_use.invalidation_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.current_use.invalidation_id)
          : value.current_use.invalidation_id !== undefined)) throw new Error('Context derivation mismatch')
    verifyContext(value.context, value.derivation.request)
    if (value.metadata.mandatory_count !== value.context.required_constraints.length || value.metadata.readiness !== value.context.readiness.status
        || value.metadata.policy_revision !== value.context.policy_version) throw new Error('Context summary mismatch')
    return value
  },
}
