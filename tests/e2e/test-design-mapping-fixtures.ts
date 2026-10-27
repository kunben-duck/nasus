import { expect, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { generationArchiveFixture, generationBudgetFixture, generationPreviewFixture } from './test-design-generation-fixtures'
import { mappingAssessment, mappingDigest } from '../../apps/portal/src/domains/quality-loop/testDesignMappingValidation'
import type { GenerationArchive, GenerationHistoryPage, GenerationJob } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'
import type { MappingArchive, MappingReview, MappingView, RecordedMappingArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignMapping'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'

export async function mappingArchiveFixture(draft: GenerationArchive, request: MappingReview, previous: Pick<MappingArchive, 'revision'> | null): Promise<MappingArchive> {
  const recorded = new Date().toISOString(), invocation = 'ui-mapping-command-' + randomUUID()
  const pin = { generation_id: draft.metadata.generation_id, artifact_hash: draft.metadata.artifact_hash,
    context_pin: draft.result.context_pin, scope_pin: draft.result.scope_pin,
    input_digest: draft.result.request.input_digest, proposal_hash: await mappingDigest(draft.result.proposal) }
  const assessment = request.mappings ? mappingAssessment(draft, request.mappings) : null
  const payload = { schema: 'nasus.test-design-mapping-review.v1', project_id: draft.metadata.project_id,
    request, generation_pin: pin, assessment, authority_actor: 'ui-independent-reviewer', invocation_id: invocation, recorded_at: recorded }
  return { revision: { project_id: draft.metadata.project_id, generation_id: draft.metadata.generation_id,
      generation_artifact_hash: draft.metadata.artifact_hash, revision_id: randomUUID(), previous_revision_id: previous?.revision.revision_id ?? null,
      sequence: (previous?.revision.sequence ?? 0) + 1, status: request.decision === 'review' ? 'reviewed' : 'withdrawn',
      artifact_hash: await mappingDigest(payload), request_hash: await mappingDigest(request), authority_actor: payload.authority_actor,
      invocation_id: invocation, recorded_at: recorded }, request, generation_pin: pin, assessment, historical_not_live: true,
    current_use: { scope_current: true, mapping_current: !!assessment, mapping_complete: !!assessment?.mapping_complete, execution_authorized: false } }
}

// Generation and review are transport fixtures, never target/model execution.
// The surrounding source/publication/context/scope setup uses the real PG API.
export async function installMappingProtocol(page: Page, scope: ScopeArchive, archive?: GenerationArchive) {
  const prepared = generationPreviewFixture({ project_id: scope.revision.project_id, scope_revision_id: scope.revision.revision_id,
    scope_artifact_hash: scope.revision.artifact_hash, model_config_id: 'ui-protocol-model', budget: generationBudgetFixture })
  const job: GenerationJob = { project_id: scope.revision.project_id, invocation_id: 'ui-mapping-generation-command',
    source_invocation_id: 'ui-mapping-generation-command', scope_revision_id: scope.revision.revision_id, status: 'completed',
    call_reserved: true, reply_archived: true, provider_outcome_unknown: false, generation_id: 'ui-mapping-generation',
    recovery_request: null, execution_authorized: false }
  if (archive) Object.assign(job, { generation_id: archive.metadata.generation_id, invocation_id: archive.metadata.invocation_id,
    source_invocation_id: archive.metadata.invocation_id })
  const draft = archive ?? generationArchiveFixture(scope, job, prepared.request)
  const state = { draft, writes: [] as MappingReview[], history: [] as RecordedMappingArchive[], pending: new Map<string, MappingReview>(),
    canReview: true, scopeCurrent: true, failRead: false, corruptRead: false, staleNext: false, inspections: 0, generationWrites: 0 }
  const head = () => state.history.at(-1) ?? null
  const current = (value: RecordedMappingArchive) => ({ ...structuredClone(value), current_use: { ...value.current_use,
    scope_current: state.scopeCurrent, mapping_current: state.scopeCurrent && head()?.revision.revision_id === value.revision.revision_id && value.revision.status === 'reviewed',
    mapping_complete: state.scopeCurrent && head()?.revision.revision_id === value.revision.revision_id && !!value.assessment?.mapping_complete } })
  await page.route('**/quality/test-design-jobs?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    const value: GenerationHistoryPage = { request: { project_id: job.project_id, scope_revision_id: scope.revision.revision_id,
      scope_artifact_hash: params.get('scope_artifact_hash')!, limit: Number(params.get('limit')), after_id: params.get('after_id')! },
      items: [{ invocation_id: job.invocation_id, source_invocation_id: job.source_invocation_id, tool_id: 'quality.test_design.generate', status: 'completed' }],
      next_after_id: null, has_running: false, generation_authorized: false, execution_authorized: false }
    await route.fulfill({ json: value })
  })
  await page.route(`**/quality/test-design-results/${job.generation_id}`, async (route) => route.fulfill({ json: draft }))
  await page.route(`**/quality/test-design-results/${job.generation_id}/mapping-review?*`, async (route) => {
    state.inspections++
    if (state.failRead) return route.fulfill({ status: 403, json: { detail: 'Explicit mapping access revocation protocol fixture' } })
    const value: MappingView = { project_id: job.project_id, generation_id: job.generation_id!, generation_artifact_hash: draft.metadata.artifact_hash,
      head: head() ? current(head()!) : null, history: state.history.map((item) => item.revision), can_review: state.canReview, scope_current: state.scopeCurrent }
    if (state.corruptRead) value.generation_artifact_hash = 'sha256:' + '0'.repeat(64)
    await route.fulfill({ json: value })
  })
  await page.route('**/quality/test-design-mapping-reviews/*', async (route) => {
    if (state.failRead) return route.fulfill({ status: 403, json: { detail: 'Explicit archived review access revocation fixture' } })
    const value = state.history.find((item) => item.revision.revision_id === new URL(route.request().url()).pathname.split('/').at(-1))!
    await route.fulfill({ json: current(value) })
  })
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON()
    if (body.tool_id === 'query.quality.test_design_job') return route.fulfill({ json: { id: randomUUID(), tool_id: body.tool_id,
      status: 'completed', input_payload: body.input, result: { test_design_job: job } } })
    if (body.tool_id === 'quality.test_design.generate') state.generationWrites++
    if (body.tool_id !== 'quality.test_design_mapping.review') return route.continue()
    expect(body.input.project_id).toBe(job.project_id)
    expect(body.input.generation_artifact_hash).toBe(draft.metadata.artifact_hash)
    const id = randomUUID(), input = structuredClone(body.input)
    state.pending.set(id, input); state.writes.push(input)
    await route.fulfill({ json: { id, tool_id: body.tool_id, status: 'waiting_confirmation', input_payload: input } })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, input = state.pending.get(id)
    if (!input) return route.continue()
    state.pending.delete(id)
    const stale = state.staleNext || input.expected_previous_revision_id !== (head()?.revision.revision_id ?? null)
    state.staleNext = false
    if (!stale) state.history.push(await mappingArchiveFixture(draft, input, head()))
    await route.fulfill({ json: { id, tool_id: 'quality.test_design_mapping.review', status: stale ? 'failed' : 'completed',
      input_payload: { ...input, confirmed_by_user: true }, result: stale ? { followup_reason: 'test_design_mapping_changed' }
        : { object_refs: ['test_design_mapping:' + head()!.revision.revision_id] } } })
  })
  return state
}
