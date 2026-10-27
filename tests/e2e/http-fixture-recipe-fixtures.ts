import { expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import type { AutomationInputPreview } from '../../apps/portal/src/domains/quality-loop/types/automationInput'
import type { FixtureRecipeRequest, FixtureRecipeView, HttpFixtureManifest } from '../../apps/portal/src/domains/quality-loop/types/httpFixtureRecipes'
import type { RunPlanArchive } from '../../apps/portal/src/domains/quality-loop/types/runPlans'

export async function fixtureDefinitionSpecimen(item: AutomationInputPreview['cases'][number]): Promise<HttpFixtureManifest> {
  // Explicit protocol data and expected values; never actual exweb execution.
  return { schema: 'nasus.http-fixture-manifest.v1', case_id: item.case_id, preconditions_digest: await canonicalDigest(item.preconditions),
    setup: ['Declared setup, not executed'], cleanup: ['Declared cleanup, not executed'], setup_steps: [
      { action: 'request', request_id: 'create', method: 'POST', path: '/fixture-protocol-only', headers_json: '{}', body_json: '{"title":"UI protocol specimen"}' },
      { action: 'capture_json', request_id: 'create', pointer: '/id', binding_id: 'fixture' },
      { action: 'assert_status', request_id: 'create', value: '201' },
      { action: 'assert_json', request_id: 'create', pointer: '/title', value_json: '"UI protocol specimen"' },
    ], cleanup_groups: { fixture: [
      { action: 'request', request_id: 'remove', method: 'DELETE', path: '/fixture-protocol-only/{{fixture}}', headers_json: '{}', body_json: 'null' },
      { action: 'assert_status', request_id: 'remove', value: '204' },
    ] } }
}
export async function installFixtureRecipeProtocol(page: Page, saved: RunPlanArchive, manifest: HttpFixtureManifest) {
  const tool = 'quality.http_fixture.register'
  const expected: FixtureRecipeRequest = { project_id: saved.metadata.project_id, run_plan_id: saved.metadata.run_plan_id,
    run_plan_artifact_hash: saved.metadata.artifact_hash, manifest }
  const commands = new Map<string, { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result?: object }>()
  const archives = new Map<string, FixtureRecipeView>()
  const state = { writes: [] as FixtureRecipeRequest[], confirms: [] as string[], reads: 0,
    loseCreateAck: false, loseConfirmAck: false, denyResolve: false, denyArchive: false, corrupt: false }
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON()
    if (body.tool_id !== tool) return route.fallback()
    expect(body.input).toEqual(expected); state.writes.push(structuredClone(body.input))
    const command = { id: 'ui-fixture-command-' + crypto.randomUUID(), tool_id: tool, status: 'waiting_confirmation',
      input_payload: { ...body.input, idempotency_key: body.idempotency_key } }
    commands.set(command.id, command)
    if (state.loseCreateAck) { state.loseCreateAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-2)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('POST'); expect(command.status).toBe('waiting_confirmation'); state.confirms.push(command.id)
    // Independent Python binding validation, not a browser-only green check.
    const view: FixtureRecipeView = JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c', `
import json,sys
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
from apps.api.app.domain.quality_loop.http_fixture_recipe import RECIPE_SCHEMA,recipe_identity,validate_recipe_archive
v=json.load(sys.stdin); p=v['saved']['artifact']['plan']; declaration=next(x for x in p['selection']['fixtures'] if x['case_id']==v['request']['manifest']['case_id'])
a=dict(schema=RECIPE_SCHEMA,project_id=p['project_id'],record_id=recipe_identity(v['command']),invocation_id=v['command'],actor_id='explicit-ui-fixture-reviewer',recorded_at='2026-10-12T00:00:00+00:00',request=v['request'],parents={'plan_digest':p['plan_digest'],**{k:p['source_pin'][k] for k in ('image_revision_id','image_artifact_hash','manifest_id','manifest_hash')}},fixture_digest=acceptance_digest(declaration))
print(json.dumps(dict(metadata=validate_recipe_archive(a,v['request'],v['saved']),archive=a,historical_not_live=True)))
`], { input: JSON.stringify({ saved, command: command.id, request: expected }), encoding: 'utf8' }))
    archives.set(view.metadata.record_id, view)
    command.status = 'completed'; command.input_payload.confirmed_by_user = true
    command.result = { invocation_id: command.id, status: 'completed', object_refs: ['http_fixture_recipe:' + view.metadata.record_id],
      http_fixture_recipe: { metadata: view.metadata, historical_not_live: true } }
    if (state.loseConfirmAck) { state.loseConfirmAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/resolve?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('tool_id') !== tool) return route.fallback()
    expect(route.request().method()).toBe('GET')
    if (state.denyResolve) return route.fulfill({ status: 503, json: { detail: 'Explicit fixture original lookup outage specimen' } })
    await route.fulfill({ json: [...commands.values()].find((c) => c.input_payload.idempotency_key === params.get('request_key')) ?? null })
  })
  await page.route('**/v1/tool-invocations/*', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-1)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('GET'); await route.fulfill({ json: command })
  })
  await page.route('**/quality/http-fixture-recipes/*', async (route) => {
    expect(route.request().method()).toBe('GET'); state.reads++
    if (state.denyArchive) return route.fulfill({ status: 403, json: { detail: 'Explicit fixture source revocation specimen' } })
    const view = structuredClone(archives.get(new URL(route.request().url()).pathname.split('/').at(-1)!)!)
    if (state.corrupt) {
      view.archive.request.manifest.setup_steps.at(-1)!.value_json = '"ALTERED_EXPECTED"'
      view.metadata.data_manifest_hash = await canonicalDigest(view.archive.request.manifest)
      view.metadata.request_hash = await canonicalDigest(view.archive.request)
      view.metadata.artifact_hash = await canonicalDigest(view.archive)
    }
    await route.fulfill({ json: view, headers: { 'Cache-Control': 'private, no-store' } })
  })
  return state
}
