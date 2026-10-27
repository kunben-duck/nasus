import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { scriptId, scriptNumber } from './automationScriptValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { ActionLocator, FrozenRouteFact, LocatorCandidate, LocatorStatus, RunPlanLocatorView } from './types/runPlanLocators'

const formats = {
  'nasus.frozen-http-route-inventory.v1': { rule: 'java.import-resolved-http-locators.v1', schema: 'nasus.run-plan-http-locators.v1', policy: 'nasus.http-locator-static-match.v1' },
  'nasus.frozen-http-route-inventory.v2': { rule: 'java.import-resolved-http-locators.v2', schema: 'nasus.run-plan-http-locators.v2', policy: 'nasus.http-locator-static-match.v2' },
} as const
const methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD', 'TRACE', 'ANY']
const flags = ['runtime_locators_verified', 'fixtures_verified', 'execution_authorized', 'business_coverage_verified']
const counts = ['automated_count', 'executed_on_target_count', 'passed_count']
const states: LocatorStatus[] = ['static_match', 'ambiguous', 'unresolved', 'not_found', 'unsupported']
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
function keys(value: unknown, expected: string[]) {
  requireRunPlan(object(value) && generationEqual(Object.keys(value).sort(), [...expected].sort()))
}
function text(value: unknown, max = 4096): value is string {
  return typeof value === 'string' && !!value && [...value].length <= max
    && ![...value].some((char) => char.codePointAt(0)! < 32 || char.codePointAt(0) === 127)
}
function path(value: unknown) {
  requireRunPlan(text(value, 1024) && !value.startsWith('/') && !value.includes('\\')
    && value.split('/').every((part) => !!part && !['.', '..', '.git'].includes(part)))
}
function codepointCompare(a: string, b: string) {
  const left = [...a], right = [...b]
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    const difference = left[i].codePointAt(0)! - right[i].codePointAt(0)!
    if (difference) return difference
  }
  return left.length - right.length
}
function uncertaintyScope(route: FrozenRouteFact) {
  const scope = route.unresolved_match_scope
  if (scope === null) return
  requireRunPlan(Array.isArray(scope) && scope.length > 0 && scope.length <= 64)
  for (const [index, item] of scope.entries()) {
    keys(item, ['method', 'route_path'])
    requireRunPlan(methods.includes(item.method) && text(item.route_path) && item.route_path.startsWith('/'))
    if (index) {
      const previous = scope[index - 1]
      requireRunPlan(codepointCompare(previous.method, item.method) < 0 || previous.method === item.method
        && codepointCompare(previous.route_path, item.route_path) < 0)
    }
  }
}
function routeShape(route: FrozenRouteFact, rule: string, scoped: boolean) {
  keys(route, ['relative_path', 'kind', 'name', 'start_line', 'end_line', 'rule', 'status', 'method', 'route_path',
    'source_file_hash', 'snippet_hash', 'supporting_spans', ...(scoped && route.status === 'unresolved' ? ['unresolved_match_scope'] : [])])
  path(route.relative_path)
  requireRunPlan(route.kind === 'route' && route.rule === rule && text(route.name)
    && scriptNumber(route.start_line) && route.start_line > 0 && scriptNumber(route.end_line) && route.end_line >= route.start_line
    && generationDigest(route.source_file_hash) && generationDigest(route.snippet_hash)
    && ['observed', 'unresolved'].includes(route.status) && Array.isArray(route.supporting_spans) && route.supporting_spans.length <= 16)
  requireRunPlan(route.status === 'observed' ? text(route.route_path) && route.route_path.startsWith('/')
    && methods.includes(route.method!)
    : route.method === null && route.route_path === null)
  if (scoped && route.status === 'unresolved') uncertaintyScope(route)
  for (const span of route.supporting_spans) {
    keys(span, ['start_line', 'end_line', 'role', 'snippet_hash'])
    requireRunPlan(scriptNumber(span.start_line) && span.start_line > 0 && scriptNumber(span.end_line) && span.end_line >= span.start_line
      && ['controller', 'class_mapping'].includes(span.role) && generationDigest(span.snippet_hash))
  }
}
function segments(value: string, template: boolean) {
  if (!value.startsWith('/') || /[%\\;*#]/u.test(value)) return null
  const parts = value.split('/'), variable = template ? /^\{[A-Za-z][A-Za-z0-9_]*\}$/u : /^\{\{[A-Za-z][A-Za-z0-9_-]{0,63}\}\}$/u
  return parts.some((part) => !variable.test(part) && (/[{}]/u.test(part) || ['.', '..'].includes(part))) ? null : parts
}
function pathMatch(value: string, template: string) {
  const actual = segments(value, false), pattern = segments(template, true)
  if (!actual || !pattern) return null
  return actual.length === pattern.length && actual.every((part, index) => /^\{[A-Za-z][A-Za-z0-9_]*\}$/u.test(pattern[index]) ? !!part : part === pattern[index])
}
function mayOverlap(value: string, template: string) {
  const actual = segments(value, false), pattern = segments(template, true)
  if (!actual || !pattern || template.includes('?')) return null
  return actual.length === pattern.length && actual.every((part, index) =>
    /^\{\{[A-Za-z][A-Za-z0-9_-]{0,63}\}\}$/u.test(part) || /^\{[A-Za-z][A-Za-z0-9_]*\}$/u.test(pattern[index]) || part === pattern[index])
}
function uncertaintyMayMatch(value: string, method: string, scope: FrozenRouteFact['unresolved_match_scope']) {
  return scope === null || scope!.some((item) => ([method, 'ANY'].includes(item.method) || ['HEAD', 'OPTIONS'].includes(method))
    && mayOverlap(value, item.route_path) !== false)
}
export function locatorQuery(plan: RunPlanArchive) {
  return { project_id: plan.metadata.project_id, run_plan_id: plan.metadata.run_plan_id, run_plan_artifact_hash: plan.metadata.artifact_hash }
}
export async function verifyRunPlanLocators(value: unknown, saved: RunPlanArchive): Promise<RunPlanLocatorView> {
  const v = value as RunPlanLocatorView, plan = saved.artifact.plan, report = v?.report, receipt = v?.receipt
  keys(v, ['receipt', 'report'])
  keys(receipt, ['schema', 'query', 'policy', 'plan_digest', 'image_revision_id', 'image_artifact_hash', 'inventory_hash', 'report_hash',
    'summary', 'historical_not_live', 'durable_locator_evidence_verified', ...flags, ...counts])
  keys(report, ['schema', 'policy', 'project_id', 'plan_digest', 'script_pin', 'source_pin', 'inventory', 'locators', 'summary', 'scope', 'report_hash', ...flags, ...counts])
  const inventory = report.inventory
  keys(inventory, ['schema', 'rule', 'provider', 'provider_version', 'sources', 'inventory_hash'])
  requireRunPlan(inventory.schema === 'nasus.frozen-http-route-inventory.v1' || inventory.schema === 'nasus.frozen-http-route-inventory.v2')
  const { rule, schema, policy } = formats[inventory.schema], scoped = inventory.schema === 'nasus.frozen-http-route-inventory.v2'
  requireRunPlan(new TextEncoder().encode(JSON.stringify(report)).length <= 4 * 1024 * 1024
    && plan.plan_digest === await canonicalDigest(Object.fromEntries(Object.entries(plan).filter(([key]) => key !== 'plan_digest')))
    && receipt.schema === 'nasus.run-plan-locator-receipt.v1' && report.schema === schema && (!scoped || plan.schema === 'nasus.run-plan.v3')
    && receipt.policy === policy && report.policy === policy && report.scope === 'fixed_source_static_method_and_path_only'
    && generationEqual(receipt.query, locatorQuery(saved)) && report.project_id === plan.project_id
    && receipt.plan_digest === plan.plan_digest && report.plan_digest === plan.plan_digest
    && receipt.image_revision_id === plan.source_pin.image_revision_id && receipt.image_artifact_hash === plan.source_pin.image_artifact_hash
    && generationEqual(report.source_pin, plan.source_pin) && generationEqual(report.script_pin, plan.script_pin)
    && receipt.historical_not_live === true && receipt.durable_locator_evidence_verified === false
    && flags.every((key) => report[key as keyof typeof report] === false && receipt[key as keyof typeof receipt] === false)
    && counts.every((key) => report[key as keyof typeof report] === 0 && receipt[key as keyof typeof receipt] === 0))
  requireRunPlan(inventory.rule === rule && inventory.provider === 'tree-sitter'
    && text(inventory.provider_version, 128) && Array.isArray(inventory.sources) && inventory.sources.length > 0 && inventory.sources.length <= 64
    && generationDigest(inventory.inventory_hash) && receipt.inventory_hash === inventory.inventory_hash
    && await canonicalDigest(Object.fromEntries(Object.entries(inventory).filter(([key]) => key !== 'inventory_hash'))) === inventory.inventory_hash
    && generationEqual(inventory.sources.map(({ pin }) => ({ binding_id: pin.binding_id, source_revision_id: pin.source_revision_id })),
      [...plan.selection.target_build.code_sources].sort((a, b) => a.binding_id < b.binding_id ? -1 : a.binding_id > b.binding_id ? 1 : 0)))
  const routes: LocatorCandidate[] = [], files = inventory.sources.flatMap((source) => source.files)
  for (const source of inventory.sources) {
    keys(source, ['pin', 'files', 'routes'])
    keys(source.pin, ['project_id', 'image_revision_id', 'image_artifact_hash', 'manifest_id', 'manifest_hash', 'binding_id', 'source_revision_id',
      'source_id', 'external_revision', 'content_hash', 'snapshot_manifest_hash'])
    requireRunPlan(Object.values(source.pin).every((item) => text(item, 128)) && Object.entries(source.pin).every(([key, item]) => !key.endsWith('hash') || generationDigest(item)))
    for (const key of ['project_id', 'image_revision_id', 'image_artifact_hash', 'manifest_id', 'manifest_hash'] as const)
      requireRunPlan(source.pin[key] === plan.source_pin[key])
    requireRunPlan(Array.isArray(source.files) && source.files.length > 0 && source.files.length <= 1000
      && new Set(source.files.map((item) => item.relative_path)).size === source.files.length && Array.isArray(source.routes) && source.routes.length <= 50000)
    for (const file of source.files) {
      keys(file, ['relative_path', 'language', 'status', 'reason', 'parser_version', 'syntax_errors', 'rules', 'source_file_hash', 'byte_count'])
      path(file.relative_path)
      requireRunPlan(text(file.language, 128) && text(file.reason) && text(file.parser_version, 128) && generationDigest(file.source_file_hash)
        && scriptNumber(file.byte_count, 8 * 1024 * 1024) && scriptNumber(file.syntax_errors, 1000)
        && ['parsed', 'unsupported', 'failed', 'not_analyzed'].includes(file.status) && (file.status !== 'parsed' || file.syntax_errors === 0)
        && Array.isArray(file.rules) && file.rules.length <= 32 && file.rules.every((item) => text(item, 128)))
    }
    for (const route of source.routes) {
      routeShape(route, rule, scoped)
      const file = source.files.find((item) => item.relative_path === route.relative_path)
      requireRunPlan(file?.status === 'parsed' && file.source_file_hash === route.source_file_hash)
      routes.push({ binding_id: source.pin.binding_id, source_revision_id: source.pin.source_revision_id,
        snapshot_manifest_hash: source.pin.snapshot_manifest_hash, ...route })
    }
  }
  const expected: ActionLocator[] = []
  for (const script of plan.proposal.scripts) for (const [index, action] of script.actions.entries()) {
    if (script.kind === 'http' && action.action !== 'request') continue
    const item: ActionLocator = { case_id: script.case_id, action_index: index, action_digest: await canonicalDigest(action),
      source_step_indices: action.source_step_indices, candidates: [], status: 'unsupported', reason: 'browser_locator_requires_original_dom_evidence' }
    if (script.kind === 'http') {
      requireRunPlan(typeof action.path === 'string' && typeof action.method === 'string' && typeof action.request_id === 'string')
      Object.assign(item, { request_id: action.request_id, method: action.method, path: action.path })
      const pathname = action.path.split('?')[0]
      let unknown = segments(pathname, false) === null || files.some((file) => file.language === 'java' && file.status !== 'parsed')
      for (const route of routes) {
        if (route.status !== 'observed') {
          if (!scoped || uncertaintyMayMatch(pathname, action.method, route.unresolved_match_scope)) unknown = true
          continue
        }
        const match = pathMatch(pathname, route.route_path!)
        if (match === null) unknown = true
        else if (match && [action.method, 'ANY'].includes(route.method!)) item.candidates.push(route)
        else if (match && ['HEAD', 'OPTIONS'].includes(action.method)) unknown = true
        else if (scoped && !match && ([action.method, 'ANY'].includes(route.method!) || ['HEAD', 'OPTIONS'].includes(action.method))
          && mayOverlap(pathname, route.route_path!) !== false) unknown = true
      }
      Object.assign(item, item.candidates.length > 1 ? { status: 'ambiguous', reason: 'multiple_static_declarations' }
        : item.candidates.length === 1 && !unknown ? { status: 'static_match', reason: 'method_and_path_only_not_runtime_dispatch' }
        : unknown ? { status: 'unresolved', reason: 'unsupported_pattern_or_request_condition' }
        : { status: files.some((file) => file.rules.includes(rule)) ? 'not_found' : 'unsupported', reason: 'no_matching_observed_declaration_not_proof_of_absence' })
    }
    expected.push(item)
  }
  requireRunPlan(Array.isArray(report.locators) && report.locators.length <= 51200 && generationEqual(report.locators, expected))
  const summary = { locator_count: expected.length, ...Object.fromEntries(states.map((status) => [status, expected.filter((item) => item.status === status).length])) }
  requireRunPlan(generationEqual(report.summary, summary) && generationEqual(receipt.summary, summary)
    && generationDigest(report.report_hash) && receipt.report_hash === report.report_hash
    && await canonicalDigest(Object.fromEntries(Object.entries(report).filter(([key]) => key !== 'report_hash'))) === report.report_hash
    && scriptId(receipt.image_revision_id))
  return v
}
