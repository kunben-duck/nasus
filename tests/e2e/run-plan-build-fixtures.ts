import { expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import type { RunPlanArchive } from '../../apps/portal/src/domains/quality-loop/types/runPlans'
import type { NativeBuildView, RunPlanBuildArchive, RunPlanBuildRequest, RunPlanBuildSelection, RunPlanBuildValue } from '../../apps/portal/src/domains/quality-loop/types/runPlanBuilds'

// Explicit transport specimens; no Java compilation, source-byte attestation or target execution.
const sample = JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_run_plan_builds import binding_inputs; v,s,b=binding_inputs(); print(json.dumps(b[0]))'], { encoding: 'utf8' })) as NativeBuildView
export const buildDeclarationSpecimen = { name: sample.receipt.artifact.path.split('/').at(-1)!, artifact: sample.receipt.artifact.content_hash,
  definition: sample.receipt.source.files.find((f) => f.path === 'pom.xml')!.content_hash }
function compile(plan: RunPlanArchive, selection: RunPlanBuildSelection, builds: NativeBuildView[]): RunPlanBuildValue {
  return JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c',
    'import json,sys; from apps.api.app.domain.quality_loop.run_plan_build import compile_run_plan_build; v=json.load(sys.stdin); print(json.dumps(compile_run_plan_build(v["plan"],v["selection"],v["builds"]),ensure_ascii=False))'],
    { input: JSON.stringify({ plan, selection, builds }), encoding: 'utf8' }))
}
export async function installBuildBindingProtocol(page: Page, plan: RunPlanArchive, current: () => boolean) {
  const builds: NativeBuildView[] = []
  for (const source of plan.artifact.plan.source_pin.source_members.filter((s) => s.source_type === 'code' && s.status === 'captured')) {
    const view = structuredClone(sample), id = 'ui-native-command-' + crypto.randomUUID(), r = view.receipt, original = plan.artifact.plan.source_pin
    Object.assign(r.source.pin, { project_id: original.project_id, image_revision_id: original.image_revision_id, image_artifact_hash: original.image_artifact_hash,
      manifest_id: original.manifest_id, manifest_hash: original.manifest_hash, binding_id: source.binding_id, source_revision_id: source.source_revision_id })
    r.request_digest = await canonicalDigest({ source: r.source, artifact_path: r.artifact.path, expected_artifact_hash: null, adapter: r.adapter })
    Object.assign(view, { project_id: original.project_id, invocation_id: id, execution_authorized: false, historical_not_live: true, status: 'completed' })
    Object.assign(view.metadata, { project_id: original.project_id, invocation_id: id, build_id: 'ui-native-build-' + crypto.randomUUID(),
      request_digest: r.request_digest, receipt_digest: await canonicalDigest(r), artifact: r.artifact })
    builds.push(view)
  }
  const state = { writes: [] as RunPlanBuildRequest[], confirms: [] as string[], reads: 0, loseCreateAck: false, loseConfirmAck: false,
    denyResolve: false, deniedResolutions: 0, denyArchive: false, builds }
  const commands = new Map<string, { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result?: object }>()
  const archives = new Map<string, RunPlanBuildArchive>()
  await page.route('**/quality/native-builds/*', async (route) => {
    expect(route.request().method()).toBe('GET'); state.reads++
    await route.fulfill({ json: builds.find((b) => route.request().url().endsWith(b.invocation_id)), headers: { 'Cache-Control': 'private, no-store' } })
  })
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON()
    if (!['query.quality.run_plan_build_preview', 'quality.run_plan.bind_native_build'].includes(body.tool_id)) return route.fallback()
    const { binding_digest: _d, source_scope_digest: _s, ...selection } = body.input as RunPlanBuildRequest
    const binding = compile(plan, selection, builds), id = 'ui-binding-command-' + crypto.randomUUID()
    if (body.tool_id === 'query.quality.run_plan_build_preview') return route.fulfill({ json: {
      id, tool_id: body.tool_id, status: 'completed', input_payload: body.input,
      result: { run_plan_build_preview: { request: { ...selection, binding_digest: binding.binding_digest, source_scope_digest: 'sha256:' + 'a'.repeat(64) },
        status: 'preview', code_source_count: builds.length, native_build_source_attested: true, target_artifact_hash: binding.target_artifact_hash,
        execution_authorized: false, remaining_gates: ['independent_build_binding_confirmation', ...binding.remaining_gates] } } } })
    expect(body.input.binding_digest).toBe(binding.binding_digest); state.writes.push(structuredClone(body.input))
    const command = { id, tool_id: body.tool_id, status: 'waiting_confirmation', input_payload: { ...body.input, idempotency_key: body.idempotency_key } }
    commands.set(id, command)
    if (state.loseCreateAck) { state.loseCreateAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, command = commands.get(id)
    if (!command) return route.fallback()
    expect(command.status).toBe('waiting_confirmation'); state.confirms.push(id)
    const { idempotency_key: _k, ...input } = command.input_payload as RunPlanBuildRequest & { idempotency_key: string }
    const { binding_digest: _d, source_scope_digest: _s, ...selection } = input
    const binding = compile(plan, selection, builds), bindingId = crypto.randomUUID()
    const artifact: RunPlanBuildArchive['artifact'] = { schema: 'nasus.run-plan-build-artifact.v1', project_id: input.project_id,
      binding_id: bindingId, actor_id: 'explicit-ui-reviewer', invocation_id: id, recorded_at: new Date().toISOString(), request: input, binding }
    archives.set(bindingId, { artifact, metadata: { project_id: input.project_id, binding_id: bindingId, invocation_id: id, actor_id: artifact.actor_id,
      recorded_at: artifact.recorded_at, artifact_hash: await canonicalDigest(artifact), request_hash: await canonicalDigest(input),
      binding_digest: binding.binding_digest, run_plan_id: input.run_plan_id, run_plan_artifact_hash: input.run_plan_artifact_hash,
      plan_digest: binding.plan_digest, image_revision_id: binding.source_pin.image_revision_id, manifest_id: binding.source_pin.manifest_id,
      target_artifact_hash: binding.target_artifact_hash }, historical_not_live: true,
      current_use: { inputs_current: current(), native_build_source_attested: true, environment_verified: false, fixtures_verified: false, execution_authorized: false } })
    command.status = 'completed'; command.input_payload.confirmed_by_user = true
    command.result = { invocation_id: id, status: 'completed', object_refs: ['run_plan_build:' + bindingId] }
    if (state.loseConfirmAck) { state.loseConfirmAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/resolve?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('tool_id') !== 'quality.run_plan.bind_native_build') return route.fallback()
    expect(route.request().method()).toBe('GET')
    if (state.denyResolve) { state.deniedResolutions++; return route.fulfill({ status: 503, json: { detail: 'Explicit lookup outage specimen' } }) }
    await route.fulfill({ json: [...commands.values()].find((c) => c.input_payload.idempotency_key === params.get('request_key')) ?? null })
  })
  await page.route('**/v1/tool-invocations/*', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-1)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('GET'); await route.fulfill({ json: command })
  })
  await page.route('**/quality/run-plan-builds/*', async (route) => {
    expect(route.request().method()).toBe('GET')
    if (state.denyArchive) return route.fulfill({ status: 403, json: { detail: 'Explicit revocation specimen' } })
    const value = structuredClone(archives.get(new URL(route.request().url()).pathname.split('/').at(-1)!)!)
    value.current_use.inputs_current = current()
    await route.fulfill({ json: value, headers: { 'Cache-Control': 'private, no-store' } })
  })
  return Object.assign(state, { archives })
}
