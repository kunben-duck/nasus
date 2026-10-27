import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { analysisApi } from './source-analysis-fixtures'
import { scopeFixture, type ScopeFixtureOptions } from './test-design-scope-fixtures'
import { newScopeContract, scopeContractValid, scopeDimensions } from '../../apps/portal/src/domains/quality-loop/testDesignScopeDraft'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'
import type { GenerationArchive, GenerationBudget, GenerationHistoryPage, GenerationHistoryRequest, GenerationJob, GenerationPreview, GenerationRequest, GenerationSelection } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'

export const fixtureDigest = `sha256:${'a'.repeat(64)}`
export async function generationScopeFixture(request: APIRequestContext, source: string, options?: ScopeFixtureOptions) {
  const v = await scopeFixture(request, source, options)
  const base = `${analysisApi}/v1/projects/${v.projectId}/quality/test-design-scopes`
  const view = await (await request.get(base, { headers: v.owner.headers, params: { context_id: v.contextId } })).json()
  const contract = newScopeContract(v.context.context)
  for (const key of scopeDimensions) {
    contract[key].applicability = 'not_applicable'
    contract[key].rationale = 'Explicit UI protocol fixture; no production behavior or execution is asserted'
  }
  for (const example of contract.examples) example.negative_not_applicable_reason = 'Synthetic protocol fixture only'
  contract.reuse_assessment = 'No test reuse claimed'
  contract.conflict_assessment = 'No fixture conflict; not a business gold assessment'
  expect(scopeContractValid(contract, v.context.context)).toBe(true)
  const pending = await v.invoke('quality.test_design_scope.review', {
    context_id: v.contextId, context_artifact_hash: v.context.metadata.artifact_hash,
    expected_previous_revision_id: null, policy_revision: 'nasus.test-design-scope.v1',
    decision: 'approve', contract, reason: 'Independent synthetic browser scope review',
  }, 'waiting_confirmation')
  await v.confirm(pending.id)
  const read = await request.get(base, { headers: v.owner.headers, params: { context_id: v.contextId } })
  expect(read.ok()).toBeTruthy()
  const scope: ScopeArchive = (await read.json()).head
  expect(scope.current_use.scope_current && scope.current_use.scope_complete).toBe(true)
  expect(view.head).toBeNull()
  return { ...v, scope }
}

export function generationPreviewFixture(selection: GenerationSelection): GenerationPreview {
  const { budget, ...pins } = selection
  return {
    request: { ...pins, input_digest: fixtureDigest, model_config_digest: fixtureDigest,
      execution: { policy_digest: fixtureDigest, plan_digest: fixtureDigest, source_binding_ids: ['ui-protocol-source'],
        source_scope_digest: fixtureDigest, budget, purpose: 'draft_test_design_source_egress' } },
    provider: 'openai_compatible', model_name: 'explicit-ui-fixture', destination: 'https://ui-fixture.example/v1',
    policy: { config_id: selection.model_config_id, provider: 'openai_compatible', model_name: 'explicit-ui-fixture',
      base_url: 'https://ui-fixture.example/v1', currency: budget.currency, context_tokens: 32768, max_output_tokens: 8192,
      input_nanos_per_token: 10000, output_nanos_per_token: 10000, tokenizer_kind: 'tiktoken',
      tokenizer_id: 'ui-fixture-tokenizer', tokenizer_digest: fixtureDigest, framing_tokens: 64, policy_id: 'ui-protocol-policy', revision: '1' },
    reservation: { currency: budget.currency, call_count: 1, estimated_input_tokens: 1024, reserved_input_tokens_per_call: 32768,
      max_output_tokens_per_call: budget.max_output_tokens_per_call, reserved_tokens: 32768 + budget.max_output_tokens_per_call,
      reserved_cost_nanos: (32768 + budget.max_output_tokens_per_call) * 10000,
      count_basis: 'local_tokenizer_with_operator_framing', cost_basis: 'operator_rate_ceiling_not_provider_invoice' },
    input_bytes: 4096, timeout_seconds: 120, call_count: 1, batching: 'one_complete_input_no_truncation',
    generation_authorized: false, execution_authorized: false, remaining_gates: ['explicit_user_confirmation'],
  }
}

export function generationArchiveFixture(scope: ScopeArchive, job: GenerationJob, request: GenerationRequest): GenerationArchive {
  const constraints = scope.assessment!.constraint_ids
  const kinds = ['acceptance_criterion', 'business_rule']
  const rows = [...constraints.map((id, index) => ({ id, kind: kinds[index] })),
    ...constraints.map((id) => ({ id, kind: 'positive_example' }))].map((item, index) => ({
    row_id: `ui-obligation-${index}`, kind: item.kind, constraint_ids: [item.id], oracle_digest: fixtureDigest,
    planned_case_ids: ['ui-draft-case'], proposed_assertion_case_ids: ['ui-draft-case'], gap_ids: [], planned: true,
    assertion_mapped: false as const, automated: false as const, executed_on_target: false as const, passed: false as const,
    unknown: true as const, mapping_status: 'pending_independent_review' as const,
  }))
  const recovery = job.invocation_id !== job.source_invocation_id ? { recovery_invocation_id: job.invocation_id } : {}
  return {
    metadata: { project_id: job.project_id, generation_id: job.generation_id!, scope_revision_id: scope.revision.revision_id,
      invocation_id: job.source_invocation_id, call_id: 'ui-native-protocol-call', status: 'draft', artifact_hash: fixtureDigest,
      case_count: 1, gap_count: 0, ...recovery },
    result: { schema: recovery.recovery_invocation_id ? 'nasus.test-design-result.v2' : 'nasus.test-design-result.v1',
      project_id: job.project_id, generation_id: job.generation_id!, invocation_id: job.source_invocation_id, ...recovery, request,
      status: 'draft', context_pin: scope.context_pin,
      scope_pin: { revision_id: scope.revision.revision_id, artifact_hash: scope.revision.artifact_hash, request_hash: scope.revision.request_hash },
      mapping_status: 'pending_independent_review', execution_authorized: false,
      proposal: { cases: [{ case_id: 'ui-draft-case', title: 'UI protocol draft, not an executed exweb test',
        preconditions: ['Synthetic response fixture'], inputs: ['Fixture request'], steps: ['Inspect fixture response'],
        global_constraint_ids: constraints.slice(1), supporting_fact_ids: [], reused_case_ids: [],
        assertions: rows.map((row, index) => ({ row_id: row.row_id, oracle_digest: fixtureDigest,
          oracle: scope.request.contract!.examples[index % constraints.length].positive, step_index: 0 })) }], gaps: [],
        coverage: { schema: 'nasus.test-design-coverage.v1', input_digest: request.input_digest, rows,
          context_pin: scope.context_pin,
          scope_pin: { revision_id: scope.revision.revision_id, artifact_hash: scope.revision.artifact_hash, request_hash: scope.revision.request_hash },
          constraint_denominator: constraints.length, obligation_denominator: rows.length, planned_constraint_count: constraints.length,
          planned_obligation_count: rows.length, gap_obligation_count: 0, unknown_count: rows.length,
          assertion_mapped_count: 0, automated_count: 0, executed_on_target_count: 0, passed_count: 0, execution_authorized: false } },
    }, historical_not_live: true, current_use: { scope_current: true, mapping_approved: false, execution_authorized: false },
  }
}

// Only the new generation/model transport is simulated. Source capture, publication,
// context, scope, authentication and page composition use the disposable PG API.
export async function installGenerationProtocol(page: Page, scope: ScopeArchive) {
  type Invocation = { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result?: unknown }
  const writes: Invocation[] = [], pending = new Map<string, Invocation>(), history: Invocation[] = []
  let preview: GenerationPreview | undefined, sourceId = '', mode: 'running' | 'complete' | 'failed-reply' | 'unknown' = 'running'
  const state = { writes, history, historyRequests: [] as GenerationHistoryRequest[], legacyHistoryReads: 0,
    previewCount: 0, jobCount: 0, modelCount: 0, failRead: false, corruptPreview: false, corruptResult: false, corruptNextPage: false,
    seedHistory: (count: number, runningIndex?: number) => {
      const prepared = generationPreviewFixture({ project_id: scope.revision.project_id, scope_revision_id: scope.revision.revision_id,
        scope_artifact_hash: scope.revision.artifact_hash, model_config_id: 'ui-tested-model', budget: generationBudgetFixture })
      for (let i = 0; i < count; i++) history.push({ id: `ui-command-a-${String(i).padStart(3, '0')}`,
        tool_id: 'quality.test_design.generate', status: i === runningIndex ? 'running' : 'failed',
        input_payload: { ...prepared.request, confirmed_by_user: true } })
    },
    modelSignature: 'ui-tested-signature', setMode: (value: typeof mode) => {
      mode = value
      const source = history.find((item) => item.id === sourceId)
      if (source && source.status !== 'cancelled') source.status = value === 'complete' ? 'completed' : value === 'running' ? 'running' : 'failed'
    } }
  const jobFor = (id: string): GenerationJob => {
    const row = history.find((item) => item.id === id)!
    const recovered = row.tool_id === 'quality.test_design.recover', archived = recovered || mode === 'complete' || mode === 'failed-reply'
    return { project_id: scope.revision.project_id, invocation_id: id, source_invocation_id: recovered ? String(row.input_payload.invocation_id) : id,
      scope_revision_id: scope.revision.revision_id, status: row.status as GenerationJob['status'], call_reserved: true, reply_archived: archived,
      provider_outcome_unknown: !archived, generation_id: row.status === 'completed' ? 'ui-generation-draft' : null,
      recovery_request: row.status === 'failed' && archived && !recovered ? { project_id: scope.revision.project_id, invocation_id: id,
        request_hash: fixtureDigest, reply_artifact_hash: fixtureDigest, response_hash: fixtureDigest } : null, execution_authorized: false }
  }
  await page.route('**/v1/settings/model-configs?route=chat', async (route) => {
    state.modelCount++
    await route.fulfill({ json: { route: 'chat', active_source: 'system_default', configurations: [
      { config_id: 'ui-tested-model', display_name: 'Explicit UI protocol model', route: 'chat', legacy_imported: false,
        last_test_result: { ok: true }, last_test_signature: state.modelSignature },
      { config_id: 'ui-legacy-model', display_name: 'Ineligible legacy model', route: 'chat', legacy_imported: true,
        last_test_result: { ok: true }, last_test_signature: 'legacy' },
      { config_id: 'ui-untested-model', display_name: 'Ineligible untested model', route: 'chat', legacy_imported: false,
        last_test_result: { ok: false }, last_test_signature: null },
    ] } })
  })
  await page.route('**/v1/tool-invocations?*', async (route) => {
    const tool = new URL(route.request().url()).searchParams.get('tool_id')
    if (!['quality.test_design.generate', 'quality.test_design.recover'].includes(tool ?? '')) return route.continue()
    state.legacyHistoryReads++
    await route.fulfill({ json: history.filter((item) => item.tool_id === tool) })
  })
  await page.route('**/quality/test-design-jobs?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    const input: GenerationHistoryRequest = { project_id: scope.revision.project_id,
      scope_revision_id: params.get('scope_revision_id')!, scope_artifact_hash: params.get('scope_artifact_hash')!,
      after_id: params.get('after_id')!, limit: Number(params.get('limit')) }
    state.historyRequests.push(input)
    expect(input.scope_revision_id).toBe(scope.revision.revision_id)
    expect(input.scope_artifact_hash).toBe(scope.revision.artifact_hash)
    expect(input.limit).toBe(20)
    if (state.failRead) return route.fulfill({ status: 403, json: { detail: 'Explicit UI history access revocation fixture' } })
    const selected = history.filter((item) => item.id > input.after_id).sort((a, b) => a.id < b.id ? -1 : 1)
    const items = selected.slice(0, input.limit).map((item) => ({ invocation_id: item.id,
      source_invocation_id: item.tool_id === 'quality.test_design.recover' ? String(item.input_payload.invocation_id) : item.id,
      tool_id: item.tool_id, status: item.status })) as GenerationHistoryPage['items']
    const value: GenerationHistoryPage = { request: input, items,
      next_after_id: selected.length > input.limit ? items.at(-1)!.invocation_id : null,
      has_running: history.some((item) => item.status === 'running'), generation_authorized: false, execution_authorized: false }
    if (state.corruptNextPage && input.after_id) value.next_after_id = input.after_id
    await route.fulfill({ json: value, headers: { 'Cache-Control': 'private, no-store' } })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, row = pending.get(id)
    if (!row) return route.continue()
    row.input_payload.confirmed_by_user = true
    if (row.tool_id === 'quality.test_design.cancel') {
      history.find((item) => item.id === row.input_payload.invocation_id)!.status = 'cancelled'
      row.status = 'completed'
    } else {
      row.status = row.tool_id === 'quality.test_design.recover' ? 'completed' : 'running'
      history.push(row)
      if (row.tool_id === 'quality.test_design.generate') sourceId = id
    }
    pending.delete(id)
    await route.fulfill({ json: row })
  })
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const body = route.request().postDataJSON(), tool: string = body.tool_id, input = body.input
    if (!['query.quality.test_design_execution', 'query.quality.test_design_job', 'quality.test_design.generate',
      'quality.test_design.recover', 'quality.test_design.cancel'].includes(tool)) return route.continue()
    const row: Invocation = { id: `ui-command-z-${randomUUID()}`, tool_id: tool, status: 'completed', input_payload: { ...input } }
    if (tool === 'query.quality.test_design_execution') {
      state.previewCount++
      preview = generationPreviewFixture(input)
      const value = structuredClone(preview)
      if (state.corruptPreview) value.reservation.reserved_tokens++
      row.result = { test_design_execution_preview: value }
    } else if (tool === 'query.quality.test_design_job') {
      state.jobCount++
      if (state.failRead) return route.fulfill({ status: 403, json: { detail: 'Explicit UI access revocation fixture' } })
      row.result = { test_design_job: jobFor(input.invocation_id) }
    } else {
      row.status = 'waiting_confirmation'; pending.set(row.id, row); writes.push(row)
    }
    await route.fulfill({ json: row })
  })
  await page.route('**/quality/test-design-results/ui-generation-draft', async (route) => {
    const row = history.at(-1)!, value = structuredClone(generationArchiveFixture(scope, jobFor(row.id), preview!.request))
    if (state.corruptResult) value.result.proposal.coverage.context_pin.artifact_hash = `sha256:${'0'.repeat(64)}`
    await route.fulfill({ json: value })
  })
  return state
}

export const generationBudgetFixture: GenerationBudget = { currency: 'USD', max_calls: 1,
  max_reserved_tokens: 65536, max_reserved_cost_nanos: 1000000000, max_input_tokens_per_call: 24576, max_output_tokens_per_call: 1024 }
