import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { createHash, randomUUID } from 'node:crypto'
import { analysisApi } from './source-analysis-fixtures'
import type { SemanticRequest, SemanticResult, SemanticPreview, SemanticHistoryItem } from '../../apps/portal/src/domains/system-image/types/semanticEvaluation'
import type { SemanticAssertion, SemanticReviewDecision, SemanticReviewPage, SemanticReviewChoice } from '../../apps/portal/src/domains/system-image/types/semanticReview'
import type { ImageRevisionSummary, ImageSemanticMember } from '../../apps/portal/src/domains/system-image/types/imageRevision'

const hash = (value: string) => `sha256:${createHash('sha256').update(value).digest('hex')}`

// Semantic/model outputs and their child membership view are protocol fixtures.
// Ingestion, original frozen evidence and source access use the real API/PG.
export async function semanticUiFixture(page: Page, request: APIRequestContext, project: string, revision: string, artifactHash: string, headers: Record<string, string>) {
  const state = { previews: 0, calls: 0, failNext: false, denyHistory: false, corruptResult: '',
    reviewCalls: 0, staleReview: false, corruptReview: '', denyReviews: false, supported: false,
    freezeCalls: 0, staleFreeze: false, frozenRevision: '', corruptFrozen: false }
  const results = new Map<string, SemanticResult>()
  const pending = new Map<string, SemanticRequest>()
  const reviewCommands = new Map<string, { assertion: SemanticAssertion; decision: SemanticReviewChoice; reason: string; previous: string | null }>()
  const decisions = new Map<string, SemanticReviewDecision[]>()
  const freezes = new Map<string, string>()
  let frozenMember: ImageSemanticMember | undefined
  let frozenHeader: ImageRevisionSummary | undefined
  function assertion(result: SemanticResult): SemanticAssertion {
    const subject = result.evaluation.judgments[0]
    const digest = hash(`${result.invocation_id}:${subject.subject_object_id}`)
    return { assertion_id: `sa_${digest.slice(7)}`, assertion_digest: digest,
      claim_id: `sc_${hash(`${revision}:${subject.subject_revision_id}:${subject.target_revision_id}:${subject.relation}`).slice(7)}`,
      project_id: project, image_revision_id: revision, image_artifact_hash: artifactHash, evaluation_id: result.invocation_id,
      evaluation_artifact_hash: result.artifact_hash, input_digest: result.request.input_digest,
      subject_object_id: subject.subject_object_id, subject_revision_id: subject.subject_revision_id,
      object_id: subject.target_object_id, object_revision_id: subject.target_revision_id, predicate: subject.relation, assessment: subject.assessment,
      subject_evidence_ids: [...new Set(result.spans.filter((s) => s.object_id === subject.subject_object_id).map((s) => s.evidence_id))].sort(),
      object_evidence_ids: [...new Set(result.spans.filter((s) => s.object_id === subject.target_object_id).map((s) => s.evidence_id))].sort(),
      evidence_digest: hash('browser review evidence'), oracle_digest: subject.oracle ? hash(JSON.stringify(subject.oracle)) : null,
      method_version: 'nasus.semantic-link-judgment.v1', semantic_kind: 'inferred', status: 'proposed', authority_status: 'pending_confirmation',
      applicability: 'selected_image_only_not_verified_coverage', can_accept: subject.assessment === 'supports' && !!subject.oracle }
  }
  const history: SemanticHistoryItem[] = []
  let preview: SemanticPreview
  const root = `${analysisApi}/v1/projects/${project}/system-image/revisions/${revision}`
  await page.route(/\/v1\/settings\/model-configs\?route=chat$/, (route) => route.fulfill({ json: {
    route: 'chat', configurations: ['A', 'B', 'Legacy'].map((name) => ({ config_id: `semantic-${name}`, route: 'chat',
      display_name: `Semantic model ${name}`, provider_kind: 'openai_compatible', base_url: 'https://semantic.example/v1',
      model_name: name, last_test_result: { ok: true }, last_test_signature: 'tested', legacy_imported: name === 'Legacy' })),
  } }))
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    if (body.tool_id === 'system_image.revisions.freeze_semantic') {
      const decision = body.input.decision_ids[0]
      expect(body.input).toEqual({ project_id: project, parent_revision_id: revision, parent_artifact_hash: artifactHash, decision_ids: [decision] })
      expect([...decisions.values()].some((chain) => chain.at(-1)?.decision_id === decision)).toBe(true)
      expect(body.idempotency_key).toBeTruthy()
      const id = randomUUID()
      freezes.set(id, decision)
      return route.fulfill({ json: { id, status: 'waiting_confirmation' } })
    }
    if (body.tool_id === 'query.system_image.links.evaluation_preview') {
      state.previews++
      const heads = [...decisions.values()].map((chain) => chain.at(-1)!).filter((head) => {
        const a = assertion(results.get(head.evaluation_id)!)
        return a.object_id === body.input.target_object_id && a.predicate === body.input.relation && body.input.subject_object_ids.includes(a.subject_object_id)
      })
      preview = { request: { ...body.input, input_digest: hash(JSON.stringify(body.input)), model_config_digest: hash(body.input.model_config_id), review_scope_digest: hash(JSON.stringify(heads)) },
        review_screening: heads.map((head) => ({ subject_object_id: assertion(results.get(head.evaluation_id)!).subject_object_id,
          head_decision_id: head.decision_id, head_decision_digest: hash(JSON.stringify(head)), claim_id: head.claim_id,
          source_image_revision_id: head.image_revision_id, decision: head.decision,
          status: head.decision === 'reject' ? 'rejected_same_revisions' : 'same_revisions_review_required',
          candidate_action: head.decision === 'reject' ? 'exclude_from_unreviewed_candidates' : 'review_before_acceptance' })),
        provider: 'openai_compatible', model_name: body.input.model_config_id, destination: 'https://semantic.example/v1',
        source_binding_ids: ['fixture-requirements-binding', 'fixture-cases-binding'], input_bytes: 2048,
        max_model_calls: 1, timeout_seconds: 60, max_output_tokens: 8192, method_version: 'nasus.semantic-link-judgment.v1',
        purpose: 'source_egress_for_proposed_semantic_review', cost_estimate_available: false }
      return route.fulfill({ json: { id: randomUUID(), status: 'completed', result: { semantic_preview: preview } } })
    }
    if (body.tool_id === 'system_image.links.evaluate') {
      expect(body.input).toEqual(preview.request)
      const id = randomUUID()
      pending.set(id, body.input)
      return route.fulfill({ json: { id, status: 'waiting_confirmation' } })
    }
    if (body.tool_id === 'system_image.links.review_semantic') {
      const a = assertion(results.get(body.input.evaluation_id)!)
      expect(body.input).toMatchObject({ project_id: project, assertion_id: a.assertion_id, assertion_digest: a.assertion_digest,
        evidence_digest: a.evidence_digest, policy_revision: 'nasus.semantic-link-review.v1', subject_object_id: a.subject_object_id })
      expect(body.input.confirmed_by_user).toBeUndefined()
      expect(body.idempotency_key).toBeTruthy()
      const id = randomUUID()
      reviewCommands.set(id, { assertion: a, decision: body.input.decision, reason: body.input.reason, previous: body.input.expected_previous_decision_id })
      return route.fulfill({ json: { id, status: 'waiting_confirmation' } })
    }
    return route.continue()
  })
  await page.route(/\/v1\/tool-invocations\/[^/]+\/confirm$/, async (route) => {
    const id = route.request().url().split('/').at(-2)!
    if (freezes.has(id)) {
      state.freezeCalls++
      if (state.staleFreeze) {
        state.staleFreeze = false
        return route.fulfill({ json: { id, status: 'failed', result: { followup_reason: 'stale_semantic_decision' } } })
      }
      const d = [...decisions.values()].flat().find((item) => item.decision_id === freezes.get(id))!
      const a = assertion(results.get(d.evaluation_id)!)
      const { assertion_id: _id, assertion_digest: _digest, claim_id: _claim, can_accept: _accept, ...snapshot } = a
      frozenMember = structuredClone({ assertion: snapshot, decision: d })
      const original = await (await request.get(`${root}?section=members&limit=1`, { headers })).json()
      state.frozenRevision = randomUUID()
      frozenHeader = { ...original.revision, image_revision_id: state.frozenRevision, policy_version: 'nasus.image-candidate.v3',
        parent_revision_id: revision, parent_artifact_hash: artifactHash, assertion_count: 1,
        artifact_hash: hash('synthetic frozen artifact'), membership_hash: hash('synthetic frozen membership') }
      return route.fulfill({ json: { id, status: 'completed', result: { object_refs: [`image_revision:${state.frozenRevision}`] } } })
    }
    const review = reviewCommands.get(id)
    if (review) {
      state.reviewCalls++
      const a = review.assertion
      const chain = decisions.get(a.claim_id) ?? []
      if (state.staleReview || (chain.at(-1)?.decision_id ?? null) !== review.previous) {
        state.staleReview = false
        return route.fulfill({ json: { id, status: 'failed', result: { followup_reason: 'stale_semantic_decision' } } })
      }
      expect(review.decision !== 'accept' || a.can_accept).toBeTruthy()
      const d: SemanticReviewDecision = { decision_id: randomUUID(), project_id: project, claim_id: a.claim_id, assertion_id: a.assertion_id,
        assertion_digest: a.assertion_digest, evidence_digest: a.evidence_digest, evaluation_id: a.evaluation_id, image_revision_id: revision,
        decision: review.decision, reason: review.reason, reviewer_actor: 'Browser reviewer fixture', recorded_at: new Date().toISOString(),
        invocation_id: id, previous_decision_id: review.previous, sequence: chain.length + 1,
        policy_revision: 'nasus.semantic-link-review.v1', applicability: 'selected_image_only_not_verified_coverage' }
      decisions.set(a.claim_id, [...chain, d])
      return route.fulfill({ json: { id, status: 'completed', result: { object_refs: [`semantic_link_decision:${d.decision_id}`] } } })
    }
    const selection = pending.get(id)
    if (!selection) return route.continue()
    state.calls++
    const item: SemanticHistoryItem = { invocation_id: id, request: selection, state: 'incomplete', artifact_hash: null,
      model_name: selection.model_config_id, recorded_at: new Date().toISOString() }
    history.push(item)
    if (state.failNext) { state.failNext = false; return route.fulfill({ json: { id, status: 'failed' } }) }
    const documents = await Promise.all([selection.target_object_id, ...selection.subject_object_ids].map(async (object) => {
      const response = await request.get(`${root}/objects/${object}/document`, { headers })
      expect(response.ok()).toBeTruthy()
      return { object, ...await response.json() }
    }))
    const spans = documents.map((doc, index) => {
      const fieldIndex = doc.fields.findIndex((field: { name: string }) => field.name === (index === 0 ? 'acceptance_criterion' : 'expected_result'))
      const field = doc.fields[fieldIndex]
      expect(field).toBeDefined()
      const evidence = doc.evidence.find((e: { start_line: number; end_line: number; snippet_hash: string }) =>
        e.start_line === field.start_line && e.end_line === field.end_line && e.snippet_hash === field.snippet_hash)
      expect(evidence).toBeDefined()
      return { span_id: hash(`${id}:${index}`), object_id: doc.object, revision_id: doc.document.document_revision_id,
        source_revision_id: doc.document.source_revision_id, evidence_id: evidence.evidence_id,
        relative_path: doc.projection.locator.relative_path, start_line: field.start_line, end_line: field.end_line,
        basis: 'projected_field' as const, role: field.name, field_index: fieldIndex, text_hash: hash(field.value), text: field.value as string }
    })
    const quotes = spans.map((span) => ({ span_id: span.span_id, start: 0, end: Array.from(span.text).length, quote: span.text, quote_hash: span.text_hash }))
    const result: SemanticResult = { invocation_id: id, artifact_hash: hash(id), request: selection,
      spans: spans.map(({ text: _text, ...span }) => span), evaluation: {
        input_digest: selection.input_digest, status: 'proposed', semantic_kind: 'inferred', calibrated_probability: null,
        authority_status: 'pending_confirmation', applicability: 'selected_image_only_not_verified_coverage',
        method_version: 'nasus.semantic-link-judgment.v1', authority_kind: 'source_projection',
        authority_object_id: spans[0].object_id, authority_revision_id: spans[0].revision_id,
        judgments: [{ subject_object_id: spans[1].object_id, subject_revision_id: spans[1].revision_id,
          target_object_id: spans[0].object_id, target_revision_id: spans[0].revision_id, relation: 'asserts', assessment: 'unknown',
          reason_summary: 'Synthetic browser contract fixture; not a live model decision.', evidence: quotes, counterevidence: [],
          unknowns: ['An approved concrete response content type is not supplied.'], oracle: null }],
      } }
    results.set(id, result)
    if (state.supported) {
      const j = result.evaluation.judgments[0]
      j.assessment = 'supports'; j.unknowns = []; j.oracle = { span_id: spans[1].span_id, expected_value: spans[1].text }
    }
    item.state = 'archived'; item.artifact_hash = result.artifact_hash
    return route.fulfill({ json: { id, status: 'completed', result: { object_refs: [`semantic_evaluation:${id}`] } } })
  })
  await page.route(/\/system-image\/revisions\?/, async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    if (frozenHeader) body.items.push(frozenHeader)
    await route.fulfill({ response, json: body })
  })
  await page.route(/\/system-image\/revisions\/[^/]+(?:\?|\/reference-proposals\?)/, async (route) => {
    const url = new URL(route.request().url())
    if (!state.frozenRevision || !url.pathname.includes(`/${state.frozenRevision}`)) return route.continue()
    if (url.pathname.endsWith('/reference-proposals')) return route.fulfill({ json: { image_revision_id: state.frozenRevision, items: [], next_after_id: null } })
    if (url.searchParams.get('section') === 'semantic_assertion_members') {
      const member = structuredClone(frozenMember!)
      if (state.corruptFrozen) member.decision.evidence_digest = hash('wrong frozen evidence')
      return route.fulfill({ json: { revision: frozenHeader, section: 'semantic_assertion_members', items: [member], total: 1, next_offset: null } })
    }
    const response = await request.get(`${root}${url.search}`, { headers })
    return route.fulfill({ json: { ...await response.json(), revision: frozenHeader } })
  })
  await page.route(/\/system-image\/revisions\/[^/]+\/semantic-evaluations\?/, (route) => {
    if (state.denyHistory) return route.fulfill({ status: 403, json: { message: 'Source access revoked' } })
    const params = new URL(route.request().url()).searchParams
    return route.fulfill({ json: { project_id: project, image_revision_id: revision, image_artifact_hash: artifactHash,
      target_object_id: params.get('target_object_id'), relation: params.get('relation'), next_after_id: null,
      items: history.filter((item) => item.request.target_object_id === params.get('target_object_id') && item.request.relation === params.get('relation')) } })
  })
  await page.route(/\/system-image\/semantic-evaluations\/[^/?]+$/, (route) => {
    const saved = results.get(route.request().url().split('/').at(-1)!)
    const result = saved && structuredClone(saved)
    if (result && state.corruptResult === 'revision') result.evaluation.judgments[0].subject_revision_id = 'foreign-revision'
    if (result && state.corruptResult === 'evidence') result.spans[0].evidence_id = 'foreign-evidence'
    if (result && state.corruptResult === 'oracle') result.evaluation.judgments[0].oracle = { span_id: result.spans[0].span_id, expected_value: 'An invented oracle' }
    if (result && state.corruptResult === 'offset') result.evaluation.judgments[0].evidence[0].end++
    return result ? route.fulfill({ json: result }) : route.fulfill({ status: 404 })
  })
  await page.route(/\/system-image\/semantic-evaluations\/[^/]+\/subjects\/[^/]+\/reviews\?/, (route) => {
    if (state.denyReviews) return route.fulfill({ status: 403, json: { message: 'Source access revoked' } })
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').at(-4)!
    const a = assertion(results.get(id)!)
    let chain = decisions.get(a.claim_id) ?? []
    const through = url.searchParams.get('through_decision_id')
    if (through !== null) chain = chain.slice(0, chain.findIndex((d) => d.decision_id === through) + 1)
    const offset = Number(url.searchParams.get('offset'))
    const end = Math.min(offset + 20, chain.length)
    const body: SemanticReviewPage = { assertion: a, policy_revision: 'nasus.semantic-link-review.v1', head_decision_id: chain.at(-1)?.decision_id ?? null,
      head: chain.at(-1) ?? null, total: chain.length, items: chain.slice(offset, end), next_offset: end < chain.length ? end : null,
      publication: 'not_in_image_membership' }
    if (state.corruptReview === 'revision') body.assertion.subject_revision_id = 'foreign-revision'
    if (state.corruptReview === 'acceptance') body.assertion.can_accept = !body.assertion.can_accept
    if (state.corruptReview === 'evidence') body.assertion.subject_evidence_ids = ['foreign-evidence']
    if (state.corruptReview === 'head') body.head_decision_id = 'foreign-head'
    return route.fulfill({ json: body })
  })
  return state
}
