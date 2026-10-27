import { expect, type Page } from '@playwright/test'
import { randomUUID, createHash } from 'node:crypto'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import { newScriptDecisions, scriptPin } from '../../apps/portal/src/domains/quality-loop/automationScriptReviewValidation'
import { scriptGates } from '../../apps/portal/src/domains/quality-loop/automationScriptValidation'
import { caseAdmissionBasis, caseAdmissionCohort } from '../../apps/portal/src/domains/quality-loop/caseApprovalValidation'
import type { CaseAdmissionPreview, CaseAdmissionRevision } from '../../apps/portal/src/domains/quality-loop/types/caseApprovals'
import { generationPreviewFixture } from './test-design-generation-fixtures'
import type { AutomationInputPreview } from '../../apps/portal/src/domains/quality-loop/types/automationInput'
import type { ScriptArchive, ScriptHistoryItem, ScriptHistoryRequest, ScriptPreview, ScriptReviewArchive, ScriptReviewRequest, ScriptSelection } from '../../apps/portal/src/domains/quality-loop/types/automationScripts'

export async function scriptPreviewFixture(selection: ScriptSelection, prepared: AutomationInputPreview): Promise<ScriptPreview> {
  const value = generationPreviewFixture({ project_id: selection.project_id, scope_revision_id: prepared.scope_pin.revision_id,
    scope_artifact_hash: prepared.scope_pin.artifact_hash, model_config_id: selection.model_config_id, budget: selection.budget })
  const plan_digest = await canonicalDigest({ original_plan: value.request.execution.plan_digest,
    case_approval_revision_id: selection.case_approval_revision_id, case_approval_artifact_hash: selection.case_approval_artifact_hash,
    http_protocol: selection.http_protocol ?? 'nasus.runner-http-execution.v1' })
  return { request: { ...selection, input_digest: prepared.input_digest, model_config_digest: value.request.model_config_digest,
      execution: { ...value.request.execution, plan_digest, policy_digest: await canonicalDigest(value.policy), purpose: 'draft_automation_source_egress' } },
    policy: value.policy, provider: value.provider, model_name: value.model_name, destination: value.destination,
    reservation: value.reservation, input_bytes: value.input_bytes, timeout_seconds: value.timeout_seconds, call_count: 1,
    generation_authorized: false, execution_authorized: false,
    remaining_gates: ['fresh_user_confirmation', 'durable_call_reservation', 'independent_script_review', 'immutable_run_plan'] }
}

export async function scriptArchiveFixture(prepared: AutomationInputPreview, preview: ScriptPreview, invocation: string): Promise<ScriptArchive> {
  const scripts: ScriptArchive['result']['proposal']['scripts'] = await Promise.all(prepared.cases.map(async (item) => ({ case_id: item.case_id, case_digest: await canonicalDigest(item), kind: 'http' as const,
    actions: [{ action: 'request', request_id: 'fixture', method: 'POST', path: '/fixture-only', headers_json: '{}', body_json: '{}',
      source_step_indices: item.steps.map((_, index) => index) }, ...item.assertions.map((a) => ({ action: 'assert_body', request_id: 'fixture',
        value: a.oracle.expected_result, source_step_indices: [a.step_index] }))],
    assertions: item.assertions.map((a, index) => ({ row_id: a.row_id, oracle_digest: a.oracle_digest, oracle: a.oracle,
      source_step_index: a.step_index, action_index: index + 1 })) })))
  if (preview.request.http_protocol === 'nasus.runner-http-execution.v2') for (const script of scripts) {
    script.actions[0].path = '/sessions/{{session}}'
    script.actions.unshift({ action: 'request', request_id: 'create', method: 'POST', path: '/sessions', headers_json: '{}', body_json: '{}', source_step_indices: [0] },
      { action: 'capture_json', request_id: 'create', pointer: '/sessionId', binding_id: 'session', source_step_indices: [0] })
    for (const assertion of script.assertions) assertion.action_index += 2
  }
  if (preview.request.http_protocol === 'nasus.runner-http-execution.v3') for (const script of scripts) {
    script.actions[0].path = '/sessions/{{session}}'
    script.actions.unshift({ action: 'use_fixture_binding', binding_id: 'session', source_step_indices: [0] })
    for (const assertion of script.assertions) assertion.action_index++
  }
  const raw_output = JSON.stringify({ input_digest: prepared.input_digest, scripts, gaps: [] })
  const response_hash = 'sha256:' + createHash('sha256').update(raw_output).digest('hex')
  const result: ScriptArchive['result'] = { schema: 'nasus.automation-script-result.v1', project_id: prepared.project_id,
    script_revision_id: 'ui-script-' + randomUUID(), invocation_id: invocation, actor_id: 'explicit-ui-author', call_id: 'ui-call-' + randomUUID(),
    response_hash, request: preview.request, model_binding: { config_id: preview.request.model_config_id,
      config_digest: preview.request.model_config_digest, provider: preview.provider, model_name: preview.model_name, base_url: preview.destination },
    prepared, raw_output, proposal: { schema: preview.request.http_protocol === 'nasus.runner-http-execution.v3' ? 'nasus.automation-script-proposal.v3'
      : preview.request.http_protocol ? 'nasus.automation-script-proposal.v2' : 'nasus.automation-script-proposal.v1',
      ...(preview.request.http_protocol ? { http_protocol: preview.request.http_protocol } : {}), input_digest: prepared.input_digest, scripts, gaps: [],
      case_count: scripts.length, script_count: scripts.length, gap_count: 0, status: 'draft', review_status: 'pending_independent_review',
      automated_count: 0, executed_on_target_count: 0, passed_count: 0, execution_authorized: false, remaining_gates: [...scriptGates] }, status: 'draft' }
  return { metadata: { project_id: prepared.project_id, script_revision_id: result.script_revision_id, invocation_id: invocation,
      call_id: result.call_id, response_hash, status: 'draft', artifact_hash: await canonicalDigest(result), input_digest: prepared.input_digest,
      mapping_revision_id: prepared.mapping_pin.revision_id, mapping_artifact_hash: prepared.mapping_pin.artifact_hash,
      script_count: scripts.length, gap_count: 0, execution_authorized: false }, result, historical_not_live: true,
    current_use: { input_current: true, execution_authorized: false } }
}

export async function scriptReviewFixture(draft: ScriptArchive, request: ScriptReviewRequest, previous: ScriptReviewArchive | null): Promise<ScriptReviewArchive> {
  const values = [...request.actions ?? [], ...request.assertions ?? []]
  const count = (decision: string) => values.filter((item) => item.decision === decision).length
  const assessment = request.decision === 'withdraw' ? null : { review_complete: !!draft.metadata.script_count && !draft.metadata.gap_count && !count('reject') && !count('defer'),
    reviewed_action_count: request.actions!.length, reviewed_oracle_count: request.assertions!.length, accepted_count: count('accept'),
    rejected_count: count('reject'), deferred_count: count('defer'), gap_count: draft.metadata.gap_count,
    automated_count: 0 as const, executed_on_target_count: 0 as const, passed_count: 0 as const, execution_authorized: false as const,
    remaining_gates: scriptGates.slice(1) }
  const script_pin = await scriptPin(draft), authority_actor = 'explicit-independent-ui-reviewer', invocation_id = 'ui-review-' + randomUUID(), recorded_at = new Date().toISOString()
  const artifact_hash = await canonicalDigest({ schema: 'nasus.automation-script-review.v1', project_id: request.project_id,
    request, script_pin, assessment, authority_actor, invocation_id, recorded_at })
  return { request, script_pin, assessment, revision: { project_id: request.project_id, script_revision_id: request.script_revision_id,
      script_artifact_hash: request.script_artifact_hash, revision_id: randomUUID(), previous_revision_id: previous?.revision.revision_id ?? null,
      sequence: (previous?.revision.sequence ?? 0) + 1, status: request.decision === 'withdraw' ? 'withdrawn' : 'reviewed', artifact_hash,
      request_hash: await canonicalDigest(request), authority_actor, invocation_id, recorded_at } }
}

// Only model/draft/review transports are specimens; source, publication and scope
// are provided by the disposable PG/MinIO API. No target or external model is run.
export async function installScriptProtocol(page: Page, prepared: AutomationInputPreview) {
  const basis = await caseAdmissionBasis(prepared), cohort_id = await caseAdmissionCohort(basis)
  const approval: CaseAdmissionRevision = { revision_id: 'ui-case-admission-' + randomUUID(), project_id: prepared.project_id,
    generation_id: prepared.generation_pin.generation_id, mapping_revision_id: prepared.mapping_pin.revision_id,
    cohort_id, previous_revision_id: null, sequence: 1, status: 'approved',
    artifact_hash: await canonicalDigest({ basis, transport: 'explicit-ui-case-admission-not-business-gold' }),
    request_hash: await canonicalDigest({ basis, decision: 'approve' }), input_digest: prepared.input_digest,
    case_count: prepared.cases.length, authority_actor: 'explicit-ui-case-reviewer', invocation_id: 'ui-admission-' + randomUUID(), recorded_at: new Date().toISOString() }
  const state = { history: [] as ScriptHistoryItem[], drafts: new Map<string, ScriptArchive>(), reviews: [] as ScriptReviewArchive[],
    writes: [] as { tool_id: string; input: unknown }[], confirmed: [] as string[], previews: 0, historyReads: 0, reviewReads: 0,
    loseGenerationAck: false, loseReviewAck: false, failHistory: false, failReview: false, corruptArchive: false,
    admission: approval, admissionStatus: 'approved' as 'approved' | 'withdrawn' | null }
  const pending = new Map<string, { tool: string; input: ScriptPreview['request'] | ScriptReviewRequest }>()
  let preview: ScriptPreview | null = null
  const head = () => state.reviews.at(-1) ?? null
  await page.route('**/v1/settings/model-configs?route=chat', (route) => route.fulfill({ json: { route: 'chat', configurations: [
    { config_id: 'ui-tested-model', display_name: 'Explicit script protocol model', route: 'chat', legacy_imported: false,
      last_test_result: { ok: true }, last_test_signature: 'explicit-tested-fixture' },
  ] } }))
  await page.route('**/quality/test-design-mapping-reviews/*/automation-input-preview?*', (route) => route.fulfill({ json: prepared }))
  await page.route('**/quality/test-design-case-approvals/preview?*', (route) => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('mapping_revision_id')).toBe(prepared.mapping_pin.revision_id)
    expect(params.get('mapping_artifact_hash')).toBe(prepared.mapping_pin.artifact_hash)
    expect(params.getAll('case_ids')).toEqual(prepared.selected_case_ids)
    const head = state.admissionStatus === null ? null : state.admissionStatus === 'approved' ? approval : {
      ...approval, revision_id: 'ui-withdrawn-admission', previous_revision_id: approval.revision_id, sequence: 2, status: 'withdrawn' as const }
    const value: CaseAdmissionPreview = { selection: { project_id: prepared.project_id,
      mapping_revision_id: prepared.mapping_pin.revision_id, mapping_artifact_hash: prepared.mapping_pin.artifact_hash,
      case_ids: prepared.selected_case_ids }, prepared, basis, cohort_id, input_current: true, can_review: true,
      head, head_revision_id: head?.revision_id ?? null, history_count: head?.sequence ?? 0,
      execution_authorized: false, business_coverage_verified: false }
    return route.fulfill({ json: value, headers: { 'Cache-Control': 'private, no-store' } })
  })
  await page.route('**/quality/automation-script-history?*', async (route) => {
    state.historyReads++
    expect(route.request().method()).toBe('GET')
    if (state.failHistory) return route.fulfill({ status: 403, json: { detail: 'Explicit source-access revocation specimen' } })
    const params = new URL(route.request().url()).searchParams
    const input: ScriptHistoryRequest = { project_id: prepared.project_id, mapping_revision_id: params.get('mapping_revision_id')!,
      mapping_artifact_hash: params.get('mapping_artifact_hash')!, after_id: params.get('after_id')!, limit: Number(params.get('limit')) }
    expect(input.mapping_revision_id).toBe(prepared.mapping_pin.revision_id)
    expect(input.mapping_artifact_hash).toBe(prepared.mapping_pin.artifact_hash)
    const remaining = state.history.filter((item) => item.invocation_id > input.after_id).sort((a, b) => a.invocation_id < b.invocation_id ? -1 : 1)
    const items = remaining.slice(0, input.limit)
    await route.fulfill({ json: { request: input, items, next_after_id: remaining.length > input.limit ? items.at(-1)!.invocation_id : null,
      generation_authorized: false, execution_authorized: false }, headers: { 'Cache-Control': 'private, no-store' } })
  })
  await page.route('**/quality/automation-script-revisions/*', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)!, value = structuredClone(state.drafts.get(id)!)
    if (state.corruptArchive) value.result.proposal.execution_authorized = true as false
    await route.fulfill({ json: value, headers: { 'Cache-Control': 'private, no-store' } })
  })
  await page.route('**/quality/automation-script-revisions/*/review?*', async (route) => {
    state.reviewReads++
    if (state.failReview) return route.fulfill({ status: 403, json: { detail: 'Explicit source-access revocation specimen' } })
    const url = new URL(route.request().url()), id = url.pathname.split('/').at(-2)!, draft = state.drafts.get(id)!
    expect(url.searchParams.get('artifact_hash')).toBe(draft.metadata.artifact_hash)
    await route.fulfill({ json: { project_id: prepared.project_id, script_revision_id: id, script_artifact_hash: draft.metadata.artifact_hash,
      script_pin: await scriptPin(draft), head: head(), history: state.reviews.map((item) => item.revision), input_current: true,
      can_review: true, execution_authorized: false }, headers: { 'Cache-Control': 'private, no-store' } })
  })
  await page.route('**/quality/automation-script-reviews/*', async (route) => route.fulfill({ json: state.reviews.find((item) =>
    item.revision.revision_id === new URL(route.request().url()).pathname.split('/').at(-1)), headers: { 'Cache-Control': 'private, no-store' } }))
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON(), tool = body.tool_id
    if (!['query.quality.automation_execution', 'quality.automation.generate', 'quality.automation.review'].includes(tool)) return route.fallback()
    const id = 'ui-script-command-z-' + randomUUID()
    if (tool === 'query.quality.automation_execution') {
      state.previews++; preview = await scriptPreviewFixture(body.input, prepared)
      return route.fulfill({ json: { id, tool_id: tool, input_payload: body.input, status: 'completed', result: { automation_execution_preview: preview } } })
    }
    state.writes.push({ tool_id: tool, input: structuredClone(body.input) }); pending.set(id, { tool, input: body.input })
    await route.fulfill({ json: { id, tool_id: tool, status: 'waiting_confirmation', input_payload: body.input } })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, command = pending.get(id)
    if (!command) return route.fallback()
    state.confirmed.push(id); pending.delete(id)
    let reference: string
    if (command.tool === 'quality.automation.generate') {
      expect(command.input).toEqual(preview!.request)
      const draft = await scriptArchiveFixture(prepared, preview!, id)
      state.drafts.set(draft.metadata.script_revision_id, draft)
      state.history.push({ invocation_id: id, status: 'completed', call_reserved: true, reply_archived: true, provider_outcome_unknown: false,
        script_revision_id: draft.metadata.script_revision_id, artifact_hash: draft.metadata.artifact_hash })
      reference = 'automation_script_revision:' + draft.metadata.script_revision_id
      if (state.loseGenerationAck) { state.loseGenerationAck = false; return route.abort('failed') }
    } else {
      const input = command.input as ScriptReviewRequest, draft = state.drafts.get(input.script_revision_id)!
      expect(input.expected_previous_revision_id).toBe(head()?.revision.revision_id ?? null)
      if (input.decision === 'review') {
        const entries = await newScriptDecisions(draft)
        expect(input.actions).toHaveLength(entries.actions.length); expect(input.assertions).toHaveLength(entries.assertions.length)
      }
      const saved = await scriptReviewFixture(draft, input, head()); state.reviews.push(saved)
      reference = 'automation_script_review:' + saved.revision.revision_id
      if (state.loseReviewAck) { state.loseReviewAck = false; return route.abort('failed') }
    }
    await route.fulfill({ json: { id, tool_id: command.tool, status: 'completed', input_payload: { ...command.input, confirmed_by_user: true },
      result: { object_refs: [reference] } } })
  })
  return state
}
