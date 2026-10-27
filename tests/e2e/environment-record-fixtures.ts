import { expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import type { RunPlanArchive } from '../../apps/portal/src/domains/quality-loop/types/runPlans'
import type { RunPlanBuildArchive } from '../../apps/portal/src/domains/quality-loop/types/runPlanBuilds'
import type { EnvironmentRecordRequest, EnvironmentRecordView } from '../../apps/portal/src/domains/quality-loop/types/environmentRecords'
import type { HealthRecordView } from '../../apps/portal/src/domains/quality-loop/types/environmentHealthRecords'

// Browser transports only: no Docker work, native deployment or business oracle.
function archive(plan: RunPlanArchive, binding: RunPlanBuildArchive, command: string, health = false, targetDown = false): EnvironmentRecordView | HealthRecordView {
  return JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c', `
import json,sys
from apps.api.app.domain.quality_loop.environment_observation_record import record_identity, environment_record_metadata, validate_environment_archive
from apps.api.app.domain.quality_loop.acceptance_specification import acceptance_digest
v=json.load(sys.stdin); p,b=v['plan']['metadata'],v['binding']['metadata']; e=v['plan']['artifact']['plan']['selection']['environment']
request=dict(project_id=p['project_id'],run_plan_id=p['run_plan_id'],run_plan_artifact_hash=p['artifact_hash'],build_binding_id=b['binding_id'],build_binding_artifact_hash=b['artifact_hash'])
instance=lambda container,image,user: dict(container_id=container*64,image_id='sha256:'+image*64,user=user,started_at='2026-10-10T00:00:00Z')
inventory=dict(schema='nasus.owned-target-environment.v1',project_id=p['project_id'],environment_id=e['environment_id'],operator_policy_digest=e['inventory_hash'],artifact_hash=b['target_artifact_hash'],target=instance('1','2','65534:65534'),dependency_instances=[dict(role='pg',**instance('4','5','999:999')),dict(role='redis',**instance('6','7','999:999'))],network_id='3'*64,namespace_origin=e['base_url'],native_artifact_attested=True,isolation_attested=True)
for key in ('host_ports_exposed','developer_resources_used','model_outbound_permitted','execution_authorized','external_egress_denial_verified','host_access_denial_verified','dependency_health_verified','fixtures_verified','locators_verified','business_coverage_verified'): inventory[key]=False
for key in ('automated_count','executed_on_target_count','passed_count'): inventory[key]=0
payload=dict(schema='nasus.run-plan-environment-record.v1',project_id=p['project_id'],record_id=record_identity(v['command']),invocation_id=v['command'],actor_id='explicit-ui-environment-reviewer',recorded_at='2026-10-10T00:00:00Z',request=request,parents={**{key:p[key] for key in ('plan_digest','image_revision_id','manifest_id')},'environment_id':e['environment_id'],'operator_policy_digest':e['inventory_hash'],'target_artifact_hash':b['target_artifact_hash']},observation=dict(inventory=inventory,inventory_hash=acceptance_digest(inventory),observed_at='2026-10-10T00:00:00Z'))
validate_environment_archive(payload,request,v['plan'],v['binding'])
if v['health']:
    import base64
    from apps.api.app.domain.shared.native_build_source import byte_digest
    from apps.api.app.domain.quality_loop.environment_health_record import health_record_identity,health_record_metadata,validate_health_archive
    from apps.api.app.domain.quality_loop.native_environment_health import HEALTH_PROBES
    instances={item['role']:item for item in inventory['dependency_instances']}; instances['target']=inventory['target']
    checks=[]
    for role,body in (('pg',b'1\\n'),('redis',b'PONG\\n'),('target',b'{"status":"DOWN"}\\n503' if v['targetDown'] else b'{"status":"UP"}\\n200')):
        checks.append(dict(role=role,probe=HEALTH_PROBES[role],**{key:instances[role][key] for key in ('container_id','image_id','started_at')},response_base64=base64.b64encode(body).decode('ascii'),response_hash=byte_digest(body),byte_count=len(body)))
    payload['schema']='nasus.run-plan-health-record.v1'; payload['record_id']=health_record_identity(v['command'])
    payload['observation'].update(schema='nasus.owned-target-health.v1',checks=checks)
    validate_health_archive(payload,request,v['plan'],v['binding']); metadata=health_record_metadata(payload)
else: metadata=environment_record_metadata(payload)
print(json.dumps(dict(metadata=metadata,archive=payload,historical_not_live=True)))
`], { input: JSON.stringify({ plan, binding, command, health, targetDown }), encoding: 'utf8' }))
}
export async function installEnvironmentRecordProtocol(page: Page, plan: RunPlanArchive, binding: RunPlanBuildArchive) {
  return installOriginalObservationProtocol(page, plan, binding, false)
}
export async function installHealthRecordProtocol(page: Page, plan: RunPlanArchive, binding: RunPlanBuildArchive) {
  return installOriginalObservationProtocol(page, plan, binding, true)
}
async function installOriginalObservationProtocol(page: Page, plan: RunPlanArchive, binding: RunPlanBuildArchive, health: boolean) {
  const tool = health ? 'quality.run_plan.record_health' : 'quality.run_plan.record_environment'
  const receipt = health ? 'run_plan_health_record' : 'run_plan_environment_record'
  const objectPrefix = health ? 'run_plan_health:' : 'run_plan_environment:'
  const resource = health ? 'run-plan-health' : 'run-plan-environments'
  const expected = { project_id: plan.metadata.project_id, run_plan_id: plan.metadata.run_plan_id, run_plan_artifact_hash: plan.metadata.artifact_hash,
    build_binding_id: binding.metadata.binding_id, build_binding_artifact_hash: binding.metadata.artifact_hash }
  const commands = new Map<string, { id: string; tool_id: string; status: string; input_payload: Record<string, unknown>; result?: object }>()
  const archives = new Map<string, EnvironmentRecordView | HealthRecordView>()
  const state = { writes: [] as EnvironmentRecordRequest[], confirms: [] as string[], reads: 0, deniedResolutions: 0,
    loseCreateAck: false, loseConfirmAck: false, denyResolve: false, denyArchive: false, targetDown: false }
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON()
    if (body.tool_id !== tool) return route.fallback()
    expect(body.input).toEqual(expected); state.writes.push(structuredClone(body.input))
    const command = { id: (health ? 'ui-health-command-' : 'ui-environment-command-') + crypto.randomUUID(), tool_id: body.tool_id,
      status: 'waiting_confirmation', input_payload: { ...body.input, idempotency_key: body.idempotency_key } }
    commands.set(command.id, command)
    if (state.loseCreateAck) { state.loseCreateAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, command = commands.get(id)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('POST'); expect(command.status).toBe('waiting_confirmation'); state.confirms.push(id)
    const value = archive(plan, binding, id, health, state.targetDown); archives.set(value.metadata.record_id, value)
    command.status = 'completed'; command.input_payload.confirmed_by_user = true
    command.result = { invocation_id: id, status: 'completed', object_refs: [objectPrefix + value.metadata.record_id],
      [receipt]: { metadata: value.metadata, historical_not_live: true } }
    if (state.loseConfirmAck) { state.loseConfirmAck = false; return route.abort('failed') }
    await route.fulfill({ json: command })
  })
  await page.route('**/v1/tool-invocations/resolve?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('tool_id') !== tool) return route.fallback()
    expect(route.request().method()).toBe('GET')
    if (state.denyResolve) { state.deniedResolutions++; return route.fulfill({ status: 503, json: { detail: 'Explicit lookup outage specimen' } }) }
    await route.fulfill({ json: [...commands.values()].find((c) => c.input_payload.idempotency_key === params.get('request_key')) ?? null })
  })
  await page.route('**/v1/tool-invocations/*', async (route) => {
    const command = commands.get(new URL(route.request().url()).pathname.split('/').at(-1)!)
    if (!command) return route.fallback()
    expect(route.request().method()).toBe('GET'); await route.fulfill({ json: command })
  })
  await page.route(`**/quality/${resource}/*`, async (route) => {
    expect(route.request().method()).toBe('GET'); state.reads++
    if (state.denyArchive) return route.fulfill({ status: 403, json: { detail: 'Explicit environment source revocation specimen' } })
    await route.fulfill({ json: archives.get(new URL(route.request().url()).pathname.split('/').at(-1)!), headers: { 'Cache-Control': 'private, no-store' } })
  })
  return state
}
