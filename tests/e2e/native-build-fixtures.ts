import { expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import type { FrozenImageSources } from '../../apps/portal/src/domains/system-image/frozenImageSources'
import type { NativeBuildCommand, NativeBuildPreview } from '../../apps/portal/src/domains/quality-loop/types/nativeBuilds'
import type { NativeBuildView } from '../../apps/portal/src/domains/quality-loop/types/runPlanBuilds'

// Native transports below are protocol specimens. Real PG/MinIO image inputs are not proof of Java compilation or target execution.
const sample = JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c',
  'import json; from apps.api.tests.test_run_plan_builds import binding_inputs; v,s,b=binding_inputs(); print(json.dumps(b[0]))'], { encoding: 'utf8' })) as NativeBuildView
export async function installNativeBuildProtocol(page: Page, sources: FrozenImageSources) {
  type Command = { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result?: object }
  const commands = new Map<string, Command>(), outputs = new Map<string, NativeBuildView>()
  const state = { writes: [] as NativeBuildCommand[], confirms: [] as string[], previewReads: 0, archiveReads: 0,
    cancelWrites: [] as { project_id: string; invocation_id: string }[], cancelConfirms: [] as string[],
    loseCancelCreateAck: false, loseCancelConfirmAck: false, denyCancelResolve: false, failCancelConfirm: false,
    loseCreateAck: false, loseConfirmAck: false, denyResolve: false, deniedResolutions: 0,
    complete() { for (const command of commands.values()) {
      if (command.status !== 'running' || command.tool_id !== 'quality.native_build.prepare') continue
      const v = outputs.get(command.id)!
      command.status = v.status = 'completed'
      command.result = { invocation_id: command.id, status: 'completed', object_refs: ['native_build:' + v.metadata.build_id] }
    } },
  }
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON()
    if (!['query.quality.native_build_preview', 'quality.native_build.prepare', 'quality.native_build.cancel'].includes(body.tool_id)) return route.fallback()
    const id = 'ui-native-' + crypto.randomUUID(), input = body.input
    if (body.tool_id === 'quality.native_build.cancel') {
      expect(commands.get(input.invocation_id)?.tool_id).toBe('quality.native_build.prepare')
      expect(input.project_id).toBe(sources.project_id)
      state.cancelWrites.push(structuredClone(input))
      const command: Command = { id, tool_id: body.tool_id, status: 'waiting_confirmation', input_payload: { ...input, idempotency_key: body.idempotency_key } }
      commands.set(id, command)
      if (state.loseCancelCreateAck) { state.loseCancelCreateAck = false; return route.abort('failed') }
      return route.fulfill({ json: command })
    }
    const source = sources.source_members.find((s) => s.source_type === 'code' && s.status === 'captured' && s.binding_id === input.binding_id)
    expect(source).toBeTruthy(); expect(input.source_revision_id).toBe(source!.source_revision_id)
    const view = structuredClone(sample), r = view.receipt
    Object.assign(r.source.pin, { ...Object.fromEntries(['project_id', 'image_revision_id', 'image_artifact_hash', 'manifest_id', 'manifest_hash'].map((k) => [k, sources[k as keyof FrozenImageSources]])),
      binding_id: source!.binding_id, source_revision_id: source!.source_revision_id })
    r.artifact.path = input.artifact_path
    r.request_digest = await canonicalDigest({ source: r.source, artifact_path: input.artifact_path, expected_artifact_hash: input.expected_artifact_hash, adapter: r.adapter })
    const policy = { adapter: r.adapter, image_id: r.toolchain.image_id as string, cache_identity_hash: 'sha256:' + 'a'.repeat(64),
      timeout_seconds: 180, network: 'none' as const, cache_access: 'read_only' as const, cache_contents_attested: false as const }
    if (body.tool_id === 'query.quality.native_build_preview') {
      state.previewReads++
      const preview: NativeBuildPreview = { request: { ...input, request_digest: r.request_digest, operator_policy_digest: await canonicalDigest(policy), source_scope_digest: 'sha256:' + 'b'.repeat(64) },
        source: { pin: r.source.pin, file_count: r.source.files.length, byte_count: r.source.files.reduce((n, f) => n + f.byte_count, 0) },
        operator_policy: policy, status: 'preview', source_execution_started: false, execution_authorized: false,
        remaining_gates: ['independent_build_confirmation', 'native_target_execution'] }
      return route.fulfill({ json: { id, tool_id: body.tool_id, status: 'completed', input_payload: input, result: { native_build_preview: preview } } })
    }
    expect(input.request_digest).toBe(r.request_digest); expect(input.operator_policy_digest).toBe(await canonicalDigest(policy))
    state.writes.push(structuredClone(input))
    const command: Command = { id, tool_id: body.tool_id, status: 'waiting_confirmation', input_payload: { ...input, idempotency_key: body.idempotency_key } }
    commands.set(id, command)
    Object.assign(view, { project_id: sources.project_id, invocation_id: id, status: 'running', historical_not_live: true, execution_authorized: false })
    Object.assign(view.metadata, { project_id: sources.project_id, invocation_id: id, build_id: 'ui-build-' + crypto.randomUUID(), request_digest: r.request_digest,
      receipt_digest: await canonicalDigest(r), artifact: r.artifact })
    outputs.set(id, view)
    if (state.loseCreateAck) { state.loseCreateAck = false; return route.abort('failed') }
    return route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/resolve?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    if (!['quality.native_build.prepare', 'quality.native_build.cancel'].includes(params.get('tool_id')!)) return route.fallback()
    expect(route.request().method()).toBe('GET')
    if (params.get('tool_id') === 'quality.native_build.cancel' ? state.denyCancelResolve : state.denyResolve) {
      state.deniedResolutions++; return route.fulfill({ status: 503, json: { detail: 'Explicit original lookup outage specimen' } })
    }
    return route.fulfill({ json: [...commands.values()].find((c) => c.tool_id === params.get('tool_id') && c.input_payload.idempotency_key === params.get('request_key')) ?? null })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, command = commands.get(id)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('POST'); expect(command.status).toBe('waiting_confirmation')
    if (command.tool_id === 'quality.native_build.cancel') {
      state.cancelConfirms.push(id)
      const target = commands.get(command.input_payload.invocation_id as string)!
      command.input_payload.confirmed_by_user = true
      if (state.failCancelConfirm) {
        state.failCancelConfirm = false; command.status = 'failed'
        command.result = { invocation_id: id, status: 'failed', object_refs: [] }
        return route.fulfill({ json: command })
      }
      if (target.status === 'running') target.status = 'cancelled'
      command.status = 'completed'; command.input_payload.confirmed_by_user = true
      command.result = { invocation_id: id, status: 'completed', object_refs: [], native_build_job: {
        project_id: sources.project_id, invocation_id: target.id, status: target.status,
        cancellation_requested: target.status === 'cancelled', cleanup_confirmed: false, execution_authorized: false } }
      if (state.loseCancelConfirmAck) { state.loseCancelConfirmAck = false; return route.abort('failed') }
      return route.fulfill({ json: command })
    }
    state.confirms.push(id); command.status = 'running'; command.input_payload.confirmed_by_user = true
    if (state.loseConfirmAck) { state.loseConfirmAck = false; return route.abort('failed') }
    return route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/*', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-1)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('GET'); return route.fulfill({ json: command })
  })
  await page.route('**/quality/native-builds/*', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)!, command = commands.get(id)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('GET'); state.archiveReads++
    return route.fulfill({ json: command.status === 'completed' ? outputs.get(id) : { project_id: sources.project_id, invocation_id: id,
      status: command.status, metadata: null, call_reserved: true, outcome_unknown: command.status !== 'running',
      worker: command.status === 'running' ? 'active' : 'expired', cleanup_confirmed: false, execution_authorized: false },
    headers: { 'Cache-Control': 'private, no-store' } })
  })
  return state
}
