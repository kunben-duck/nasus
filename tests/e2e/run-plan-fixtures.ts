import { expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import type { ScriptArchive, ScriptReviewArchive } from '../../apps/portal/src/domains/quality-loop/types/automationScripts'
import type { RunPlanArchive, RunPlanRequest, RunPlanSelection, RunPlanSources, RunPlanValue } from '../../apps/portal/src/domains/quality-loop/types/runPlans'

function compile(selection: RunPlanSelection, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources): RunPlanValue {
  return JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c',
    'import json,sys; from apps.api.app.domain.quality_loop.run_plan import compile_run_plan; v=json.load(sys.stdin); print(json.dumps(compile_run_plan(v["draft"],v["review"],v["selection"],v["sources"]),ensure_ascii=False))'],
    { input: JSON.stringify({ selection, draft, review, sources }), encoding: 'utf8' }))
}
// Canonical command and plan transports below are explicit protocol specimens.
// Source pages use the disposable native PostgreSQL/MinIO API; no target is run.
export async function installRunPlanProtocol(page: Page, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources, current: () => boolean) {
  const state = { writes: [] as RunPlanRequest[], confirms: [] as string[], previews: 0, reads: 0,
    loseCreateAck: false, loseConfirmAck: false, denyArchive: false, denyResolve: false, deniedResolutions: 0 }
  const commands = new Map<string, { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result?: object }>()
  const archives = new Map<string, RunPlanArchive>()
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON(), selection = body.input as RunPlanRequest
    if (!['query.quality.run_plan_preview', 'quality.run_plan.prepare'].includes(body.tool_id)) return route.fallback()
    const { plan_digest: _p, source_scope_digest: _s, ...input } = selection
    const plan = compile(input, draft, review, sources)
    expect(selection.project_id).toBe(draft.metadata.project_id)
    const id = 'ui-plan-command-' + crypto.randomUUID()
    if (body.tool_id === 'query.quality.run_plan_preview') {
      state.previews++
      return route.fulfill({ json: { id, tool_id: body.tool_id, status: 'completed', input_payload: selection, result: {
        run_plan_preview: { request: { ...selection, plan_digest: plan.plan_digest, source_scope_digest: 'sha256:' + 'a'.repeat(64) },
          case_count: plan.prepared.cases.length, obligation_count: plan.prepared.obligation_denominator, status: 'preview',
          target_verification: plan.target_verification, execution_authorized: false,
          remaining_gates: ['fresh_prepare_confirmation', ...plan.remaining_gates] } } } })
    }
    expect(selection.plan_digest).toBe(plan.plan_digest)
    state.writes.push(structuredClone(selection))
    const command = { id, tool_id: body.tool_id, status: 'waiting_confirmation', input_payload: { ...selection, idempotency_key: body.idempotency_key } }
    commands.set(id, command)
    if (state.loseCreateAck) { state.loseCreateAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, command = commands.get(id)
    if (!command) return route.fallback()
    expect(command.status).toBe('waiting_confirmation'); state.confirms.push(id)
    const input = Object.fromEntries(Object.entries(command.input_payload).filter(([key]) => key !== 'idempotency_key')) as unknown as RunPlanRequest
    const selection = Object.fromEntries(Object.entries(input).filter(([key]) => !['plan_digest', 'source_scope_digest'].includes(key))) as unknown as RunPlanSelection
    const plan = compile(selection, draft, review, sources)
    const artifact: RunPlanArchive['artifact'] = { schema: selection.policy_revision === 'nasus.run-plan.v3' ? 'nasus.run-plan-artifact.v3'
      : selection.policy_revision === 'nasus.run-plan.v2' ? 'nasus.run-plan-artifact.v2' : 'nasus.run-plan-artifact.v1', project_id: input.project_id, run_plan_id: crypto.randomUUID(),
      invocation_id: id, actor_id: 'explicit-ui-plan-reviewer', recorded_at: new Date().toISOString(), request: input, plan }
    const metadata: RunPlanArchive['metadata'] = { project_id: input.project_id, run_plan_id: artifact.run_plan_id, invocation_id: id,
      artifact_hash: await canonicalDigest(artifact), request_hash: await canonicalDigest(input), plan_digest: input.plan_digest, status: 'prepared',
      actor_id: artifact.actor_id, recorded_at: artifact.recorded_at, context_id: plan.prepared.context_pin.context_id,
      image_revision_id: sources.image_revision_id, manifest_id: sources.manifest_id, script_revision_id: input.script_revision_id,
      review_revision_id: input.review_revision_id, execution_authorized: false }
    archives.set(artifact.run_plan_id, { metadata, artifact, historical_not_live: true,
      current_use: { inputs_current: current(), target_verified: false, execution_authorized: false } })
    command.status = 'completed'; command.input_payload.confirmed_by_user = true
    command.result = { invocation_id: id, status: 'completed', object_refs: ['run_plan:' + artifact.run_plan_id] }
    if (state.loseConfirmAck) { state.loseConfirmAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/resolve?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('tool_id') !== 'quality.run_plan.prepare') return route.fallback()
    expect(route.request().method()).toBe('GET')
    if (state.denyResolve) {
      state.deniedResolutions++
      return route.fulfill({ status: 503, json: { detail: 'Explicit original-command lookup outage specimen' } })
    }
    await route.fulfill({ json: [...commands.values()].find((item) => item.input_payload.idempotency_key === params.get('request_key')) ?? null })
  })
  await page.route('**/v1/tool-invocations/*', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-1)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('GET'); await route.fulfill({ json: command })
  })
  await page.route('**/quality/run-plans/*', async (route) => {
    state.reads++; expect(route.request().method()).toBe('GET')
    if (state.denyArchive) return route.fulfill({ status: 403, json: { detail: 'Explicit revocation specimen' } })
    const value = structuredClone(archives.get(new URL(route.request().url()).pathname.split('/').at(-1)!)!)
    value.current_use.inputs_current = current()
    await route.fulfill({ json: value, headers: { 'Cache-Control': 'private, no-store' } })
  })
  return Object.assign(state, { archives })
}
