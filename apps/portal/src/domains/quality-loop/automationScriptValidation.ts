import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { strictJson } from '../../shared/utils/strictJson'
import { generationDigest, generationEqual, verifyGenerationPreview } from './testDesignGenerationValidation'
import { verifyAutomationInput } from './automationInputValidation'
import { compareMappingIds } from './testDesignMappingPartitions'
import type { AutomationInputPreview } from './types/automationInput'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'
import type { ScriptArchive, ScriptHistoryItem, ScriptHistoryPage, ScriptHistoryRequest, ScriptPreview, ScriptSelection } from './types/automationScripts'

export function requireScript(valid: unknown): asserts valid { if (!valid) throw new Error('Fixed script provenance could not be verified') }
export const scriptId = (value: unknown): value is string => typeof value === 'string' && !!value && [...value].length <= 128
export const scriptNumber = (value: unknown, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= max
export const scriptGates = ['independent_script_review', 'target_build_environment_binding', 'api_or_dom_locator_evidence', 'fixture_setup_cleanup', 'immutable_run_plan']
export function verifyScriptHistory(value: unknown, input: ScriptHistoryRequest): ScriptHistoryPage {
  const v = value as ScriptHistoryPage
  requireScript(v && generationEqual(v.request, input) && Object.keys(v).length === 5 && scriptId(input.project_id)
    && scriptId(input.mapping_revision_id) && generationDigest(input.mapping_artifact_hash) && scriptNumber(input.limit, 20) && input.limit > 0
    && typeof input.after_id === 'string' && input.after_id.length <= 128 && Array.isArray(v.items) && v.items.length <= input.limit
    && v.generation_authorized === false && v.execution_authorized === false)
  for (const [i, item] of v.items.entries()) requireScript(item && Object.keys(item).length === 7 && scriptId(item.invocation_id)
    && item.invocation_id > (i ? v.items[i - 1].invocation_id : input.after_id) && ['running', 'completed', 'failed', 'cancelled'].includes(item.status)
    && [item.call_reserved, item.reply_archived, item.provider_outcome_unknown].every((x) => typeof x === 'boolean')
    && (!item.reply_archived || item.call_reserved) && item.provider_outcome_unknown === (item.call_reserved && !item.reply_archived)
    && (item.script_revision_id === null ? item.artifact_hash === null : scriptId(item.script_revision_id) && generationDigest(item.artifact_hash) && item.reply_archived)
    && (item.status !== 'completed' || item.script_revision_id !== null))
  requireScript(v.next_after_id === null || v.items.length === input.limit && v.next_after_id === v.items.at(-1)?.invocation_id)
  return v
}
export async function verifyScriptPreview(value: unknown, selection: ScriptSelection, prepared: AutomationInputPreview): Promise<ScriptPreview> {
  const v = value as ScriptPreview, r = v?.request
  requireScript(r && Object.entries(selection).every(([key, item]) => generationEqual(item, r[key as keyof typeof r]))
    && scriptId(r.case_approval_revision_id) && generationDigest(r.case_approval_artifact_hash)
    && r.http_protocol === selection.http_protocol
    && (r.http_protocol === undefined || ['nasus.runner-http-execution.v2', 'nasus.runner-http-execution.v3'].includes(r.http_protocol))
    && r.input_digest === prepared.input_digest && r.execution?.purpose === 'draft_automation_source_egress'
    && generationEqual(r.case_ids, prepared.selected_case_ids) && r.mapping_revision_id === prepared.mapping_pin.revision_id
    && r.mapping_artifact_hash === prepared.mapping_pin.artifact_hash && r.project_id === prepared.project_id
    && generationEqual(v.remaining_gates, ['fresh_user_confirmation', 'durable_call_reservation', 'independent_script_review', 'immutable_run_plan'])
    && await canonicalDigest(v.policy) === r.execution.policy_digest)
  verifyGenerationPreview({ ...v, batching: 'one_complete_input_no_truncation', request: { project_id: r.project_id,
    scope_revision_id: prepared.scope_pin.revision_id, scope_artifact_hash: prepared.scope_pin.artifact_hash,
    input_digest: r.input_digest, model_config_id: r.model_config_id, model_config_digest: r.model_config_digest,
    execution: { ...r.execution, purpose: 'draft_test_design_source_egress' } } }, { project_id: r.project_id,
    scope_revision_id: prepared.scope_pin.revision_id, scope_artifact_hash: prepared.scope_pin.artifact_hash,
    model_config_id: r.model_config_id, budget: r.budget })
  requireScript(v.call_count === 1 && !('batching' in v) && !('batch_planning' in v))
  return v
}
const assertActions = new Set(['assert_text', 'assert_visible', 'assert_url', 'assert_status', 'assert_json', 'assert_header', 'assert_body'])
export function scriptProtocol(proposal: ScriptArchive['result']['proposal']) {
  if (proposal.schema === 'nasus.automation-script-proposal.v1' && !('http_protocol' in proposal)) return 'nasus.runner-http-execution.v1'
  requireScript(proposal.schema === 'nasus.automation-script-proposal.v2' && proposal.http_protocol === 'nasus.runner-http-execution.v2'
    || proposal.schema === 'nasus.automation-script-proposal.v3' && proposal.http_protocol === 'nasus.runner-http-execution.v3')
  return proposal.http_protocol
}
const hasControlCharacter = (value: string) => [...value].some((char) => char.codePointAt(0)! < 32 || char.codePointAt(0) === 127)
const bindingJson = (value: string) => strictJson(value, { maxContainerDepth: 64, maxNumberLength: 256, safeIntegerNumbers: true })
export function verifyHttpBindingActions(actions: { action: string; [field: string]: unknown }[], requireSourceIndices = true, allowFixtureImports = false) {
  const requests = new Set<string>(), bindings = new Set<string>()
  let fixtureImports = 0
  const fields: Record<string, string[]> = { request: ['request_id', 'method', 'path', 'headers_json', 'body_json'],
    capture_json: ['request_id', 'pointer', 'binding_id'], assert_status: ['request_id', 'value'],
    assert_json: ['request_id', 'pointer', 'value_json'], assert_header: ['request_id', 'name', 'value'], assert_body: ['request_id', 'value'] }
  if (allowFixtureImports) fields.use_fixture_binding = ['binding_id']
  requireScript(Array.isArray(actions) && actions.length > 0 && actions.length <= 100)
  for (const action of actions) {
    requireScript(Object.hasOwn(fields, action.action))
    const operands = fields[action.action]
    const hasIndices = Object.hasOwn(action, 'source_step_indices')
    requireScript((!requireSourceIndices || hasIndices) && operands && Object.keys(action).length === operands.length + 1 + Number(hasIndices) && operands.every((key) =>
      typeof action[key] === 'string' && (key === 'pointer' || !!action[key].trim()) && action[key].length <= 4096 && !hasControlCharacter(action[key])))
    if (hasIndices) requireScript(Array.isArray(action.source_step_indices) && action.source_step_indices.length > 0
      && action.source_step_indices.length <= 512 && new Set(action.source_step_indices).size === action.source_step_indices.length
      && action.source_step_indices.every((index) => Number.isSafeInteger(index) && index >= 0 && index < 512))
    if (action.action === 'use_fixture_binding') {
      const binding = action.binding_id as string
      requireScript(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/u.test(binding) && !bindings.has(binding) && bindings.size < 32 && ++fixtureImports <= 16)
      bindings.add(binding)
      continue
    }
    const request = action.request_id as string
    requireScript(scriptId(request) && /^[\p{L}\p{N}_-]+$/u.test(request))
    if (action.action === 'request') {
      const path = action.path as string, [pathname, ...query] = path.split('?')
      requireScript(!requests.has(request) && ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].includes(action.method as string)
        && path.startsWith('/') && !path.startsWith('//') && !/[\\#]/u.test(path) && !/[{}]/u.test(query.join('?')))
      for (const segment of pathname.split('/')) {
        const binding = /^\{\{([A-Za-z][A-Za-z0-9_-]{0,63})\}\}$/u.exec(segment)
        requireScript(binding ? bindings.has(binding[1]) : !/[{}]/u.test(segment))
      }
      const headers = bindingJson(action.headers_json as string), body = bindingJson(action.body_json as string)
      requireScript(headers !== null && typeof headers === 'object' && !Array.isArray(headers) && Object.keys(headers).length <= 2
        && Object.entries(headers).every(([key, value]) => ['Accept', 'Content-Type'].includes(key) && typeof value === 'string'
          && !!value.trim() && value.length <= 256 && !hasControlCharacter(value))
        && (!['GET', 'HEAD'].includes(action.method as string) || body === null))
      requests.add(request)
    } else {
      requireScript(requests.has(request))
      if (action.action === 'capture_json' || action.action === 'assert_json') requireScript(action.pointer === ''
        || typeof action.pointer === 'string' && action.pointer.startsWith('/') && !/~(?![01])/u.test(action.pointer))
      if (action.action === 'capture_json') {
        const binding = action.binding_id as string
        requireScript(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/u.test(binding) && !bindings.has(binding) && bindings.size < 32)
        bindings.add(binding)
      } else if (action.action === 'assert_json') bindingJson(action.value_json as string)
      else if (action.action === 'assert_status') requireScript(/^[1-5][0-9]{2}$/u.test(action.value as string))
      else if (action.action === 'assert_header') requireScript(/^[A-Za-z0-9-]{1,128}$/u.test(action.name as string))
    }
  }
}
function verifyBindingActions(script: ScriptArchive['result']['proposal']['scripts'][number], allowFixtureImports: boolean) {
  verifyHttpBindingActions(script.actions, true, allowFixtureImports)
}
export async function verifyScriptArchive(value: unknown, draft: GenerationArchive, mapping: RecordedMappingArchive, item: ScriptHistoryItem): Promise<ScriptArchive> {
  const v = value as ScriptArchive, m = v?.metadata, r = v?.result, p = r?.proposal
  requireScript(m && r && p && m.project_id === draft.metadata.project_id && m.script_revision_id === item.script_revision_id
    && m.artifact_hash === item.artifact_hash && m.invocation_id === item.invocation_id && m.status === 'draft' && r.status === 'draft'
    && r.schema === 'nasus.automation-script-result.v1' && v.historical_not_live === true
    && typeof v.current_use?.input_current === 'boolean' && v.current_use.execution_authorized === false
    && m.execution_authorized === false && ['project_id', 'script_revision_id', 'invocation_id', 'call_id', 'response_hash'].every((key) =>
      generationEqual(m[key as keyof typeof m], r[key as keyof typeof r])) && scriptId(r.actor_id) && scriptId(r.call_id)
    && typeof r.raw_output === 'string' && r.raw_output.length <= 1024 * 1024 && r.raw_output.trim().startsWith('{'))
  const admitted = r.request.case_approval_revision_id !== undefined
  requireScript(admitted ? scriptId(r.request.case_approval_revision_id) && generationDigest(r.request.case_approval_artifact_hash)
    : r.request.case_approval_artifact_hash === undefined && v.current_use.input_current === false)
  requireScript(!v.current_use.input_current || draft.current_use.scope_current && mapping.current_use.scope_current
    && mapping.current_use.mapping_current && mapping.current_use.mapping_complete)
  requireScript(await canonicalDigest(r) === m.artifact_hash)
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(r.raw_output))
  requireScript('sha256:' + Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join('') === r.response_hash)
  await verifyAutomationInput(r.prepared, draft, mapping, { caseIds: r.request.case_ids, historical: true })
  requireScript(r.request.project_id === m.project_id && r.request.mapping_revision_id === mapping.revision.revision_id
    && r.request.mapping_artifact_hash === mapping.revision.artifact_hash && r.request.input_digest === r.prepared.input_digest
    && m.mapping_revision_id === r.request.mapping_revision_id && m.mapping_artifact_hash === r.request.mapping_artifact_hash
    && m.input_digest === r.request.input_digest && r.model_binding.config_id === r.request.model_config_id
    && r.model_binding.config_digest === r.request.model_config_digest
    && scriptProtocol(p) === (r.request.http_protocol ?? 'nasus.runner-http-execution.v1')
    && p.input_digest === r.request.input_digest && p.status === 'draft' && p.review_status === 'pending_independent_review'
    && p.execution_authorized === false && p.automated_count === 0 && p.executed_on_target_count === 0 && p.passed_count === 0
    && Array.isArray(p.scripts) && Array.isArray(p.gaps) && p.script_count === p.scripts.length && p.gap_count === p.gaps.length
    && p.case_count === r.prepared.cases.length && p.case_count === p.script_count + p.gap_count
    && m.script_count === p.script_count && m.gap_count === p.gap_count && generationEqual(p.remaining_gates, scriptGates))
  const raw = strictJson(r.raw_output) as Pick<typeof p, 'input_digest' | 'scripts' | 'gaps'>
  requireScript(raw.input_digest === p.input_digest && Array.isArray(raw.scripts) && Array.isArray(raw.gaps)
    && Object.keys(raw).length === 3
    && generationEqual([...raw.scripts].sort((a, b) => compareMappingIds(a.case_id, b.case_id)), p.scripts)
    && generationEqual([...raw.gaps].sort((a, b) => compareMappingIds(a.case_id, b.case_id)), p.gaps))
  const accounted = new Set<string>()
  for (const script of [...p.scripts, ...p.gaps]) {
    const original = r.prepared.cases.find((c) => c.case_id === script.case_id)
    requireScript(original && !accounted.has(script.case_id) && await canonicalDigest(original) === script.case_digest)
    accounted.add(script.case_id)
    if (!('actions' in script)) { requireScript(typeof script.description === 'string' && !!script.description.trim()); continue }
    requireScript(['http', 'browser'].includes(script.kind) && Array.isArray(script.actions) && script.actions.length > 0 && script.actions.length <= 256
      && Array.isArray(script.assertions) && script.assertions.length === original.assertions.length)
    if (script.kind === 'http' && r.request.http_protocol) verifyBindingActions(script, r.request.http_protocol === 'nasus.runner-http-execution.v3')
    else requireScript(script.actions.every((action) => !['capture_json', 'use_fixture_binding'].includes(action.action)))
    const steps = new Set<number>(), rows = new Set<string>(), actionIndices = new Set<number>()
    for (const action of script.actions) {
      requireScript(Array.isArray(action.source_step_indices) && !!action.source_step_indices.length && new Set(action.source_step_indices).size === action.source_step_indices.length
        && action.source_step_indices.every((i) => scriptNumber(i, original.steps.length - 1)))
      action.source_step_indices.forEach((i) => steps.add(i))
    }
    requireScript(steps.size === original.steps.length)
    for (const binding of script.assertions) {
      const oracle = original.assertions.find((a) => a.row_id === binding.row_id), action = script.actions[binding.action_index]
      requireScript(oracle && action && scriptNumber(binding.action_index, script.actions.length - 1) && !rows.has(binding.row_id)
        && !actionIndices.has(binding.action_index) && binding.source_step_index === oracle.step_index
        && binding.oracle_digest === oracle.oracle_digest && generationEqual(binding.oracle, oracle.oracle)
        && assertActions.has(action.action) && action.source_step_indices.includes(oracle.step_index))
      rows.add(binding.row_id); actionIndices.add(binding.action_index)
    }
    requireScript(script.actions.filter((a) => assertActions.has(a.action)).length === actionIndices.size)
  }
  requireScript(accounted.size === r.prepared.cases.length)
  return v
}
