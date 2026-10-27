import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { LinkCandidatePage } from './linkCandidateApi'
import type { SemanticHistory, SemanticHistoryItem, SemanticPreview, SemanticRequest, SemanticResult, SemanticSelection } from './types/semanticEvaluation'

const root = (project: string) => `/v1/projects/${encodeURIComponent(project)}/system-image`
const digest = (value: string) => /^sha256:[0-9a-f]{64}$/.test(value)
function requireScope(value: SemanticSelection, page: LinkCandidatePage) {
  if (value.project_id !== page.project_id || value.image_revision_id !== page.image_revision_id
      || value.expected_image_hash !== page.image_artifact_hash || value.target_object_id !== page.target.object_id
      || value.relation !== page.relation) throw new Error('Semantic scope mismatch')
}
function sameRequest(a: SemanticRequest, b: SemanticRequest) {
  return Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([key, value]) =>
    JSON.stringify(value) === JSON.stringify(b[key as keyof SemanticRequest]))
}
export const semanticEvaluationApi = {
  async preview(selection: SemanticSelection) {
    const result = await platformApi.invokeTool({ tool_id: 'query.system_image.links.evaluation_preview',
      idempotency_key: crypto.randomUUID(), input: { ...selection } })
    const preview = result.result?.semantic_preview as SemanticPreview | undefined
    if (result.status !== 'completed' || !preview || !Object.entries(selection).every(([key, value]) =>
      JSON.stringify(value) === JSON.stringify(preview.request[key as keyof SemanticRequest]))
      || !digest(preview.request.input_digest) || !digest(preview.request.model_config_digest)
      || !preview.request.review_scope_digest || !digest(preview.request.review_scope_digest)
      || !Array.isArray(preview.review_screening) || preview.review_screening.length > 64
      || preview.review_screening.some((item) => !selection.subject_object_ids.includes(item.subject_object_id)
        || !digest(item.head_decision_digest) || !item.head_decision_id || !item.claim_id || !item.source_image_revision_id
        || !['accept', 'reject', 'defer'].includes(item.decision)
        || !['rejected_same_revisions', 'identity_unresolved', 'different_endpoints', 'stale_requires_review', 'same_revisions_review_required'].includes(item.status))
      || preview.max_model_calls !== 1 || preview.timeout_seconds !== 60 || preview.max_output_tokens !== 8192
      || preview.method_version !== 'nasus.semantic-link-judgment.v1' || preview.cost_estimate_available !== false
      || preview.purpose !== 'source_egress_for_proposed_semantic_review' || !preview.source_binding_ids.length
      || !Number.isInteger(preview.input_bytes) || preview.input_bytes <= 0 || preview.input_bytes > 256 * 1024) {
      throw new Error('Semantic preview could not be verified')
    }
    const destination = new URL(preview.destination)
    if (destination.protocol !== 'https:' || destination.username || destination.password || destination.search || destination.hash) {
      throw new Error('Semantic destination could not be verified')
    }
    return { preview, attemptKey: crypto.randomUUID() }
  },
  async execute(preview: SemanticPreview, attemptKey: string) {
    if (preview.review_screening.some((item) => ['rejected_same_revisions', 'identity_unresolved', 'different_endpoints'].includes(item.status))) {
      throw new Error('Historical review blocks model egress')
    }
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.links.evaluate', idempotency_key: attemptKey,
      input: { ...preview.request } })
    if (pending.status !== 'waiting_confirmation') throw new Error('Explicit semantic confirmation required')
    const result = await platformApi.confirmToolInvocation(pending.id)
    if (result.status !== 'completed' || !result.result?.object_refs.includes(`semantic_evaluation:${result.id}`)) {
      throw new Error('Semantic evaluation did not complete; do not retry this call')
    }
    return result.id
  },
  async history(page: LinkCandidatePage, afterId: string, signal: AbortSignal) {
    const params = new URLSearchParams({ target_object_id: page.target.object_id, relation: page.relation, after_id: afterId })
    const history = await request<SemanticHistory>(`${root(page.project_id)}/revisions/${encodeURIComponent(page.image_revision_id)}/semantic-evaluations?${params}`,
      { signal, cache: 'no-store' })
    if (history.project_id !== page.project_id || history.image_revision_id !== page.image_revision_id
        || history.image_artifact_hash !== page.image_artifact_hash || history.target_object_id !== page.target.object_id
        || history.relation !== page.relation) throw new Error('Semantic history scope mismatch')
    for (const item of history.items) {
      requireScope(item.request, page)
      if (!['archived', 'incomplete'].includes(item.state)) throw new Error('Unknown semantic history state')
    }
    return history
  },
  async result(page: LinkCandidatePage, item: Pick<SemanticHistoryItem, 'invocation_id' | 'request' | 'artifact_hash'>, signal: AbortSignal) {
    const result = await request<SemanticResult>(`${root(page.project_id)}/semantic-evaluations/${encodeURIComponent(item.invocation_id)}`, { signal, cache: 'no-store' })
    requireScope(result.request, page)
    const evaluation = result.evaluation
    if (result.invocation_id !== item.invocation_id || !sameRequest(result.request, item.request) || !digest(result.artifact_hash)
        || (item.artifact_hash && result.artifact_hash !== item.artifact_hash) || evaluation.input_digest !== item.request.input_digest
        || evaluation.status !== 'proposed' || evaluation.semantic_kind !== 'inferred' || evaluation.calibrated_probability !== null
        || evaluation.authority_status !== 'pending_confirmation' || evaluation.applicability !== 'selected_image_only_not_verified_coverage'
        || evaluation.method_version !== 'nasus.semantic-link-judgment.v1' || evaluation.authority_kind !== 'source_projection'
        || evaluation.authority_object_id !== page.target.object_id || evaluation.authority_revision_id !== page.target.revision_id
        || evaluation.judgments.length !== item.request.subject_object_ids.length) throw new Error('Semantic result scope mismatch')
    const subjects = new Set(evaluation.judgments.map((judgment) => judgment.subject_object_id))
    if (subjects.size !== item.request.subject_object_ids.length || item.request.subject_object_ids.some((id) => !subjects.has(id))) {
      throw new Error('Semantic result subjects mismatch')
    }
    if (new Set(result.spans.map((span) => span.span_id)).size !== result.spans.length) throw new Error('Duplicate semantic spans')
    for (const span of result.spans) {
      const endpoint = span.object_id === page.target.object_id ? page.target : page.items.find((candidate) => candidate.endpoint.object_id === span.object_id)?.endpoint
      if ((!subjects.has(span.object_id) && span.object_id !== page.target.object_id)
          || (endpoint && (span.revision_id !== endpoint.revision_id || span.source_revision_id !== endpoint.source_revision_id
            || !endpoint.evidence_ids.includes(span.evidence_id)))
          || !digest(span.text_hash) || !['source_excerpt', 'projected_field'].includes(span.basis)
          || !Number.isInteger(span.start_line) || !Number.isInteger(span.end_line) || span.start_line < 1 || span.end_line < span.start_line) {
        throw new Error('Semantic span scope mismatch')
      }
    }
    for (const judgment of evaluation.judgments) {
      const subject = page.items.find((candidate) => candidate.endpoint.object_id === judgment.subject_object_id)?.endpoint
      if (judgment.target_object_id !== page.target.object_id || judgment.target_revision_id !== page.target.revision_id
          || (subject && judgment.subject_revision_id !== subject.revision_id)
          || judgment.relation !== page.relation || !['supports', 'contradicts', 'unrelated', 'unknown'].includes(judgment.assessment)) {
        throw new Error('Semantic judgment mismatch')
      }
      for (const quote of [...judgment.evidence, ...judgment.counterevidence]) {
        const span = result.spans.find((s) => s.span_id === quote.span_id)
        if (!span || ![page.target.object_id, judgment.subject_object_id].includes(span.object_id)
            || span.revision_id !== (span.object_id === page.target.object_id ? page.target.revision_id : judgment.subject_revision_id)
            || !Number.isInteger(quote.start) || !Number.isInteger(quote.end) || quote.start < 0 || quote.end <= quote.start
            || Array.from(quote.quote).length !== quote.end - quote.start || !digest(quote.quote_hash)) {
          throw new Error('Semantic citation mismatch')
        }
      }
      if (judgment.oracle) {
        const span = result.spans.find((s) => s.span_id === judgment.oracle!.span_id)
        if (judgment.relation !== 'asserts' || span?.object_id !== judgment.subject_object_id || span.role !== 'expected_result'
            || span.basis !== 'projected_field' || !judgment.oracle.expected_value.trim()
            || ![...judgment.evidence, ...judgment.counterevidence].some((quote) => quote.span_id === span.span_id)) {
          throw new Error('Semantic oracle scope mismatch')
        }
      } else if (judgment.relation === 'asserts' && judgment.assessment === 'supports') throw new Error('Semantic oracle missing')
    }
    return result
  },
}
