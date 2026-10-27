import { expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import type { RunPlanArchive } from '../../apps/portal/src/domains/quality-loop/types/runPlans'
import type { RunPlanLocatorView } from '../../apps/portal/src/domains/quality-loop/types/runPlanLocators'
import type { LocatorRecordRequest, LocatorRecordView } from '../../apps/portal/src/domains/quality-loop/types/runPlanLocatorRecords'

export async function installLocatorProtocol(page: Page, saved: RunPlanArchive) {
  // Parser and matcher are real; this explicitly constructed source is UI protocol data, not exweb runtime evidence.
  const value: RunPlanLocatorView = JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c', `
import json,sys
from types import SimpleNamespace
from apps.api.tests.test_run_plan_locators import frozen_source
from apps.api.app.infrastructure.system_image.frozen_http_locators import FrozenHttpLocatorInventory
from apps.api.app.domain.quality_loop.http_locator_evidence import compile_http_locator_evidence
from apps.api.app.application.quality_loop.run_plan_locators import RunPlanLocatorQuery,RunPlanLocatorApplicationService
saved=json.load(sys.stdin); plan=saved['artifact']['plan']; sources={}
java=b'''import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("") class Controller {
@PostMapping("/fixture-only") String fixture() { return "ok"; }
@PostMapping("/sessions") String create() { return "ok"; }
@PostMapping("/sessions/{sessionId}") String session() { return "ok"; }
}'''
if plan['schema']=='nasus.run-plan.v3':
    java=java.replace(b'\\n}',b'\\n@PostMapping(path="/unrelated-condition",headers="X-Mode=x") String conditional() { return "ok"; }\\n}')
for index,pin in enumerate(plan['selection']['target_build']['code_sources']):
    single={**plan,'selection':{**plan['selection'],'target_build':{**plan['selection']['target_build'],'code_sources':[pin]}}}
    bodies={'Controller.java':java,'pom.xml':b'<project/>'} if index==0 else {'pom.xml':b'<project/>'}
    sources[pin['binding_id']]=frozen_source(single,bodies)
port=FrozenHttpLocatorInventory(SimpleNamespace(read=lambda **selection:sources[selection['binding_id']]))
report=compile_http_locator_evidence(plan,port.inspect(plan,require_access=lambda:None))
query=RunPlanLocatorQuery(project_id=plan['project_id'],run_plan_id=saved['metadata']['run_plan_id'],run_plan_artifact_hash=saved['metadata']['artifact_hash'])
print(json.dumps(dict(receipt=RunPlanLocatorApplicationService._receipt(query,plan,report),report=report)))`],
    { input: JSON.stringify(saved), encoding: 'utf8' }))
  const state = { reads: 0, deny: false, corrupt: false, value }
  await page.route('**/quality/run-plans/*/http-locators?*', async (route) => {
    state.reads++
    expect(route.request().method()).toBe('GET')
    const url = new URL(route.request().url())
    expect(url.pathname.split('/').at(-2)).toBe(saved.metadata.run_plan_id)
    expect(url.searchParams.get('run_plan_artifact_hash')).toBe(saved.metadata.artifact_hash)
    if (state.deny) return route.fulfill({ status: 403, json: { detail: 'Explicit locator source-revocation specimen' } })
    const result = structuredClone(value)
    if (state.corrupt) {
      result.report.locators[0].action_digest = 'sha256:' + 'b'.repeat(64)
      const { report_hash: _hash, ...body } = result.report
      result.report.report_hash = result.receipt.report_hash = await canonicalDigest(body)
    }
    await route.fulfill({ json: result, headers: { 'Cache-Control': 'private, no-store' } })
  })
  return state
}

export async function installLocatorRecordProtocol(page: Page, saved: RunPlanArchive, observation: RunPlanLocatorView) {
  const tool = 'quality.run_plan.record_locators'
  const expected = { project_id: saved.metadata.project_id, run_plan_id: saved.metadata.run_plan_id, run_plan_artifact_hash: saved.metadata.artifact_hash }
  const commands = new Map<string, { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result?: object }>()
  const archives = new Map<string, LocatorRecordView>()
  const state = { writes: [] as LocatorRecordRequest[], confirms: [] as string[], reads: 0,
    loseCreateAck: false, loseConfirmAck: false, denyResolve: false, denyArchive: false, corrupt: false }
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON()
    if (body.tool_id !== tool) return route.fallback()
    expect(body.input).toEqual(expected); state.writes.push(structuredClone(body.input))
    const command = { id: 'ui-locator-command-' + crypto.randomUUID(), tool_id: tool, status: 'waiting_confirmation',
      input_payload: { ...body.input, idempotency_key: body.idempotency_key } }
    commands.set(command.id, command)
    if (state.loseCreateAck) { state.loseCreateAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-2)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('POST'); expect(command.status).toBe('waiting_confirmation'); state.confirms.push(command.id)
    // Independent Python domain validation of UI protocol data; never actual target execution.
    const view: LocatorRecordView = JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c', `
import json,sys
from apps.api.app.domain.quality_loop.http_locator_record import LOCATOR_RECORD_SCHEMA,locator_record_identity,validate_locator_archive
v=json.load(sys.stdin); p=v['saved']['artifact']['plan']
a=dict(schema=LOCATOR_RECORD_SCHEMA,project_id=p['project_id'],record_id=locator_record_identity(v['command']),invocation_id=v['command'],actor_id='explicit-ui-locator-reviewer',recorded_at='2026-10-11T00:00:00+00:00',request=v['request'],parents={'plan_digest':p['plan_digest'],**{k:p['source_pin'][k] for k in ('image_revision_id','image_artifact_hash','manifest_id','manifest_hash')}},report=v['report'])
print(json.dumps(dict(metadata=validate_locator_archive(a,v['request'],v['saved']),archive=a,historical_not_live=True)))
`], { input: JSON.stringify({ saved, command: command.id, request: expected, report: observation.report }), encoding: 'utf8' }))
    archives.set(view.metadata.record_id, view)
    command.status = 'completed'; command.input_payload.confirmed_by_user = true
    command.result = { invocation_id: command.id, status: 'completed', object_refs: ['run_plan_locators:' + view.metadata.record_id],
      run_plan_locator_record: { metadata: view.metadata, historical_not_live: true } }
    if (state.loseConfirmAck) { state.loseConfirmAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/resolve?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('tool_id') !== tool) return route.fallback()
    expect(route.request().method()).toBe('GET')
    if (state.denyResolve) return route.fulfill({ status: 503, json: { detail: 'Explicit original locator lookup outage specimen' } })
    await route.fulfill({ json: [...commands.values()].find((c) => c.input_payload.idempotency_key === params.get('request_key')) ?? null })
  })
  await page.route('**/v1/tool-invocations/*', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-1)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('GET'); await route.fulfill({ json: command })
  })
  await page.route('**/quality/run-plan-locators/*', async (route) => {
    expect(route.request().method()).toBe('GET'); state.reads++
    if (state.denyArchive) return route.fulfill({ status: 403, json: { detail: 'Explicit original locator revocation specimen' } })
    const view = structuredClone(archives.get(new URL(route.request().url()).pathname.split('/').at(-1)!)!)
    if (state.corrupt) {
      view.archive.report.locators.pop()
      const { report_hash: _hash, ...report } = view.archive.report
      view.archive.report.report_hash = view.metadata.report_hash = await canonicalDigest(report)
      view.metadata.artifact_hash = await canonicalDigest(view.archive)
    }
    await route.fulfill({ json: view, headers: { 'Cache-Control': 'private, no-store' } })
  })
  return state
}
