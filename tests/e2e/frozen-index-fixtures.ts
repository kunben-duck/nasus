import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { createHash, randomUUID } from 'node:crypto'
import { analysisApi, type captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions } from './image-revision-fixtures'
import type { FrozenIndexStatus, IndexBuildRequest, IndexGeneration, IndexPreview, PublicationPin } from '../../apps/portal/src/domains/system-image/types/frozenIndex'
import type { ContextRetrievalPlan } from '../../apps/portal/src/domains/system-image/types/contextRetrievalPlan'

export async function publishIndexFixture(request: APIRequestContext, v: Awaited<ReturnType<typeof captureAnalysis>>) {
  const image = (await frozenRevisions(request, v.projectId, v.owner.headers))[0]
  const root = `${analysisApi}/v1/projects/${v.projectId}/system-image`
  const response = await request.get(`${root}/publications/preview`, { headers: v.owner.headers, params: {
    image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash, target_baseline_id: image.baseline_id,
  } })
  expect(response.ok()).toBeTruthy()
  const preview = await response.json()
  const pending = await v.invoke('system_image.revisions.review_publication', { ...preview.target,
    expected_preview_digest: preview.preview_digest, expected_review_id: preview.review?.review_id ?? null,
    decision: 'approve', reason: 'Static browser index fixture, not business approval' }, 'waiting_confirmation')
  const approved = await request.post(`${analysisApi}/v1/tool-invocations/${pending.id}/confirm`, { headers: v.owner.headers })
  expect(approved.ok()).toBeTruthy()
  const done = await approved.json()
  expect(done.status).toBe('completed')
  await v.invoke('baseline.promote', { ...preview.target, expected_preview_digest: preview.preview_digest,
    approval_id: done.result.object_refs[0].split(':')[1] })
  const current = await request.get(root, { headers: v.owner.headers })
  expect(current.ok()).toBeTruthy()
  return (await current.json()).read_state.pin as PublicationPin
}

// The browser boundary uses explicit model/index transport fixtures, not external egress.
// Source capture, publication and the initial empty index status use real API/PG.
// Native embedding, canonical build, atomic commit and status have separate PG API tests.
export async function indexBrowserFixture(page: Page, project: string, pin: PublicationPin, binding: string) {
  const hash = (value: string) => `sha256:${createHash('sha256').update(value).digest('hex')}`
  const state = { previews: 0, writes: 0, confirmations: 0, fail: false, corruptPreview: false, corruptStatus: false, changedModel: false,
    queryPlans: 0, queryCount: 2, corruptPlan: '', holdPlan: false, releasePlan: () => {},
    queryWrites: 0, queryConfirmations: 0, queryStatus: '', queryId: '', corruptQueryResult: false,
    generation: null as IndexGeneration | null, release: () => {} }
  let preview: IndexPreview
  let queryPlan: ContextRetrievalPlan
  let queryInput: Record<string, unknown>
  const queryJob = () => ({ id: state.queryId, tool_id: 'system_image.context.retrieve', status: state.queryStatus, input_payload: queryInput })
  const commands = new Map<string, IndexBuildRequest>()
  await page.route(`**/projects/${project}/system-image/indexes/*/context-query-plan?**`, async (route) => {
    const generation = state.generation
    if (!generation) return route.continue()
    state.queryPlans++
    expect(new URL(route.request().url()).searchParams.get('publication_id')).toBe(pin.publication_id)
    const queryCount = state.queryCount
    const plan: ContextRetrievalPlan = { request: { project_id: project, publication_id: pin.publication_id,
      generation_id: generation.generation_id, method_version: 'nasus.context-retrieval-plan.v1' },
      publication_pin: { ...pin }, index_artifact_hash: generation.artifact_hash, model: generation.model,
      source_binding_ids: queryCount ? [binding] : [], query_count: queryCount, input_bytes: queryCount * 100,
      max_query_bytes: queryCount ? 100 : 0, max_model_calls: Math.ceil(queryCount / 32), batch_size: 32, timeout_per_call_seconds: 60,
      max_query_count: 256, query_byte_limit: 4096, total_byte_limit: 1048576, queries_digest: hash('explicit-query-fixture'),
      plan_digest: hash('explicit-plan-fixture'), state: queryCount ? 'prepared' : 'missing_requirements',
      source_policy: 'frozen_ac_and_parent_description_only', execution_available: true, model_calls_made: 0,
      cost_estimate_available: false, relationship_authority: false, quality_generation_authorized: false, rerank_egress_authorized: false }
    queryPlan = plan
    const value = { ...plan, ...(state.corruptPlan === 'budget' ? { max_model_calls: 0 } : {}),
      ...(state.corruptPlan === 'authority' ? { quality_generation_authorized: true } : {}) }
    if (state.corruptPlan === 'scope') value.publication_pin.publication_id = 'wrong-publication'
    if (state.holdPlan) await new Promise<void>((resolve) => { state.releasePlan = resolve })
    await route.fulfill({ json: value })
  })
  await page.route('**/v1/tool-invocations?tool_id=system_image.context.retrieve', (route) => route.fulfill({ json: state.queryId ? [queryJob()] : [] }))
  await page.route(`**/projects/${project}/system-image/context-retrievals/*`, (route) => route.fulfill({ json: {
    schema: 'nasus.context-retrieval.v1', project_id: project, invocation_id: state.queryId,
    publication_pin: pin, generation_id: state.generation!.generation_id, index_artifact_hash: state.generation!.artifact_hash,
    model: queryPlan.model, plan_digest: queryPlan.plan_digest, queries_digest: queryPlan.queries_digest, query_count: queryPlan.query_count,
    retrieval_bindings: Object.fromEntries(Array.from({ length: queryPlan.query_count }, (_, i) => [`fixture-ac-${i}`, `fixture-trace-${i}`])),
    queries: Array.from({ length: queryPlan.query_count }, (_, i) => ({ target_id: `fixture-ac-${i}`, retrieval_id: `fixture-trace-${i}`,
      query_hash: hash(`query-${i}`), artifact_hash: hash(`trace-${i}`) })),
    batches: [{ ordinal: 0, artifact_hash: hash('query-batch'), fallback: false }],
    relationship_authority: state.corruptQueryResult, quality_generation_authorized: false, rerank_egress_authorized: false,
  } }))
  await page.route(/\/v1\/settings\/model-configs\?route=embedding$/, (route) => route.fulfill({ json: {
    route: 'embedding', configurations: ['A', 'B', 'Legacy', 'Untested', 'Gemini'].map((name) => ({
      config_id: `embedding-${name}`, display_name: `Embedding ${name}`, route: 'embedding', model_name: name,
      provider_kind: name === 'Gemini' ? 'gemini' : 'openai_compatible', base_url: 'https://embedding.example/v1',
      last_test_signature: 'browser-tested-fixture', last_test_result: { ok: name !== 'Untested' },
      last_tested_at: '2026-09-19T00:00:00Z', legacy_imported: name === 'Legacy',
    })),
  } }))
  await page.route(`**/projects/${project}/system-image/indexes?**`, async (route) => {
    if (!state.generation) return route.continue()
    const value: FrozenIndexStatus = { project_id: project, publication_pin: { ...pin },
      state: state.changedModel ? 'rebuild_required' : 'ready', generation: state.generation, can_build: true, quality_generation_authorized: false }
    if (state.corruptStatus) value.publication_pin.publication_id = 'wrong-publication'
    await route.fulfill({ json: value })
  })
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    if (body.tool_id === 'system_image.context.retrieve') {
      state.queryWrites++
      expect(body.input).toEqual({ ...queryPlan.request, expected_plan_digest: queryPlan.plan_digest })
      expect(body.idempotency_key).toBeTruthy()
      state.queryId = randomUUID(); state.queryStatus = 'waiting_confirmation'; queryInput = body.input
      return route.fulfill({ json: queryJob() })
    }
    if (body.tool_id === 'system_image.context.cancel_retrieval') {
      expect(body.input).toEqual({ project_id: project, invocation_id: state.queryId })
      state.queryStatus = 'cancelled'
      return route.fulfill({ json: { id: randomUUID(), tool_id: body.tool_id, status: 'completed' } })
    }
    if (body.tool_id === 'query.system_image.index.preview') {
      state.previews++
      expect(body.input).toMatchObject({ project_id: project, publication_id: pin.publication_id, method_version: 'nasus.frozen-evidence-index.v1' })
      preview = { request: { ...body.input, input_digest: hash(JSON.stringify(body.input)), model_config_digest: hash(body.input.model_config_id) },
        publication_pin: { ...pin }, model: { config_id: body.input.model_config_id, provider: 'openai_compatible', model_name: 'browser-embedding-fixture',
          base_url: 'https://embedding.example/v1', config_digest: hash(body.input.model_config_id) },
        source_binding_ids: [binding], document_count: 64, input_bytes: 8192, max_model_calls: 2, batch_size: 32, timeout_per_call_seconds: 60,
        cost_estimate_available: false, query_egress: 'Explicit fixture retrieval query consent', rerank_egress_authorized: false, quality_generation_authorized: false }
      if (state.corruptPreview) preview.publication_pin.image_artifact_hash = hash('wrong-image')
      return route.fulfill({ json: { id: randomUUID(), tool_id: body.tool_id, status: 'completed', result: { index_preview: preview } } })
    }
    if (body.tool_id !== 'system_image.index.build') return route.continue()
    state.writes++
    expect(body.idempotency_key).toBeTruthy()
    expect(body.input).toEqual(preview.request)
    expect(body.input.confirmed_by_user).toBeUndefined()
    const id = randomUUID()
    commands.set(id, body.input)
    return route.fulfill({ json: { id, tool_id: body.tool_id, status: 'waiting_confirmation',
      input_payload: { ...body.input, idempotency_key: body.idempotency_key } } })
  })
  await page.route(/\/v1\/tool-invocations\/[^/]+\/confirm$/, async (route) => {
    const id = route.request().url().split('/').at(-2)!, input = commands.get(id)
    if (id === state.queryId) {
      state.queryConfirmations++; state.queryStatus = 'running'
      return route.fulfill({ json: queryJob() })
    }
    if (!input) return route.continue()
    state.confirmations++
    await new Promise<void>((resolve) => { state.release = resolve })
    if (state.fail) return route.fulfill({ json: { id, tool_id: 'system_image.index.build', status: 'failed' } })
    state.generation = { project_id: project, generation_id: id, request: input, publication_pin: pin,
      model: preview.model, document_count: preview.document_count, dimensions: 3, artifact_hash: hash(id), quality_generation_authorized: false }
    await route.fulfill({ json: { id, tool_id: 'system_image.index.build', status: 'completed', result: { object_refs: [`image_index:${id}`] } } })
  })
  return state
}
