import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { strictJson } from '../../shared/utils/strictJson'
import { verifyHttpBindingActions } from './automationScriptValidation'
import { exactKeys, identity, originalObservationIdentity, utc } from './environmentRecordValidation'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { FixtureRecipeArchive, FixtureRecipeMetadata, FixtureRecipeRequest, FixtureRecipeView, HttpFixtureManifest, HttpFixtureAction } from './types/httpFixtureRecipes'

export const fixtureRecipeIdentity = (command: string) => originalObservationIdentity(command, 'nasus:http-fixture-recipe:')
export const fixtureLimits = { bytes: 128 * 1024, steps: 400, resources: 16 }
const text = (value: unknown, limit = 2000) => typeof value === 'string' && !!value.trim()
  && [...value].length <= limit && ![...value].some((char) => char.codePointAt(0)! < 32 || char.codePointAt(0) === 127)
const arrayEqual = (a: Set<string>, b: Set<string>) => generationEqual([...a].sort(), [...b].sort())
// Match the server's UTF-8 size check, including default JSON separators.
const serialized = (value: unknown): string => Array.isArray(value) ? '[' + value.map(serialized).join(', ') + ']'
  : value !== null && typeof value === 'object' ? '{' + Object.entries(value).map(([key, item]) => JSON.stringify(key) + ': ' + serialized(item)).join(', ') + '}'
    : JSON.stringify(value)
function pathBindings(path: string) {
  const [pathname, ...query] = path.split('?')
  requireRunPlan(!/[{}]/u.test(query.join('?')))
  const bindings = new Set<string>()
  for (const part of pathname.split('/')) {
    const match = /^\{\{([A-Za-z][A-Za-z0-9_-]{0,63})\}\}$/u.exec(part)
    requireRunPlan(match || !/[{}]/u.test(part))
    if (match) bindings.add(match[1])
  }
  return bindings
}
export function verifyFixtureManifest(value: unknown): HttpFixtureManifest {
  const v = value as HttpFixtureManifest
  exactKeys(v, ['schema', 'case_id', 'preconditions_digest', 'setup', 'cleanup', 'setup_steps', 'cleanup_groups'])
  requireRunPlan(v.schema === 'nasus.http-fixture-manifest.v1' && text(v.case_id, 128) && generationDigest(v.preconditions_digest)
    && new TextEncoder().encode(serialized(v)).length <= fixtureLimits.bytes)
  for (const items of [v.setup, v.cleanup]) requireRunPlan(Array.isArray(items) && items.length > 0 && items.length <= 64 && items.every((item) => text(item)))
  verifyHttpBindingActions(v.setup_steps, false)
  const requests = new Map<string, HttpFixtureAction>(), captures = new Set<string>(), resources = new Set<string>(), assertions = new Set<string>()
  for (const [index, step] of v.setup_steps.entries()) {
    const id = step.request_id as string
    if (step.action === 'request') {
      requireRunPlan(['GET', 'HEAD', 'POST'].includes(step.method as string))
      requests.set(id, step)
      if (step.method === 'POST') requireRunPlan(v.setup_steps[index + 1]?.action === 'capture_json' && v.setup_steps[index + 1]?.request_id === id)
    } else if (step.action === 'capture_json') {
      requireRunPlan(requests.get(id)?.method === 'POST' && !captures.has(id))
      captures.add(id); resources.add(step.binding_id as string)
    } else if (step.action === 'assert_status') assertions.add(id)
  }
  requireRunPlan(arrayEqual(assertions, new Set(requests.keys())) && resources.size > 0 && resources.size <= fixtureLimits.resources)
  exactKeys(v.cleanup_groups, [...resources])
  let count = v.setup_steps.length
  for (const [binding, steps] of Object.entries(v.cleanup_groups)) {
    requireRunPlan(Array.isArray(steps) && steps.length > 0)
    const cleanupRequests = new Set<string>(), cleanupAssertions = new Set<string>()
    let mutations = 0
    const resolved = steps.map((step) => {
      requireRunPlan(step && typeof step === 'object' && step.action !== 'capture_json')
      if (step.action === 'request') {
        requireRunPlan(typeof step.path === 'string' && arrayEqual(pathBindings(step.path), new Set([binding])))
        cleanupRequests.add(step.request_id as string)
        mutations += Number(!['GET', 'HEAD', 'OPTIONS'].includes(step.method as string))
        return { ...step, path: step.path.replace(/\{\{([A-Za-z][A-Za-z0-9_-]{0,63})\}\}/gu, 'fixture_validation_resource') }
      }
      if (step.action === 'assert_status') cleanupAssertions.add(step.request_id as string)
      return step
    })
    verifyHttpBindingActions(resolved, false)
    requireRunPlan(mutations > 0 && arrayEqual(cleanupRequests, cleanupAssertions))
    count += steps.length
  }
  requireRunPlan(count <= fixtureLimits.steps)
  return v
}
export async function fixtureRecipeRequest(plan: RunPlanArchive, value: unknown): Promise<FixtureRecipeRequest> {
  const manifest = verifyFixtureManifest(value), p = plan.artifact.plan
  requireRunPlan(plan.metadata.project_id === plan.artifact.project_id && p.project_id === plan.metadata.project_id
    && p.source_pin.project_id === p.project_id && plan.metadata.run_plan_id === plan.artifact.run_plan_id
    && plan.metadata.invocation_id === plan.artifact.invocation_id && plan.metadata.plan_digest === p.plan_digest
    && plan.metadata.image_revision_id === p.source_pin.image_revision_id && plan.metadata.manifest_id === p.source_pin.manifest_id
    && plan.metadata.artifact_hash === await canonicalDigest(plan.artifact))
  const declarations = p.selection.fixtures.filter((item) => item.case_id === manifest.case_id)
  requireRunPlan(declarations.length === 1 && await canonicalDigest(manifest) === declarations[0].data_manifest_hash
    && ['case_id', 'preconditions_digest', 'setup', 'cleanup'].every((key) => generationEqual(manifest[key as keyof HttpFixtureManifest], declarations[0][key as keyof typeof declarations[0]])))
  return { project_id: plan.metadata.project_id, run_plan_id: plan.metadata.run_plan_id,
    run_plan_artifact_hash: plan.metadata.artifact_hash, manifest }
}
export async function parseFixtureRecipe(plan: RunPlanArchive, source: string) {
  requireRunPlan(new TextEncoder().encode(source).length <= fixtureLimits.bytes)
  return fixtureRecipeRequest(plan, strictJson(source, { maxContainerDepth: 64, maxNumberLength: 256, safeIntegerNumbers: true }))
}
export async function expectedFixtureMetadata(a: FixtureRecipeArchive): Promise<FixtureRecipeMetadata> {
  return { schema: a.schema, project_id: a.project_id, record_id: a.record_id, invocation_id: a.invocation_id,
    actor_id: a.actor_id, recorded_at: a.recorded_at, run_plan_id: a.request.run_plan_id, run_plan_artifact_hash: a.request.run_plan_artifact_hash,
    ...a.parents, case_id: a.request.manifest.case_id, data_manifest_hash: await canonicalDigest(a.request.manifest),
    fixture_digest: a.fixture_digest, request_hash: await canonicalDigest(a.request), artifact_hash: await canonicalDigest(a),
    status: 'recorded', historical_not_live: true, recipe_bytes_verified: true, fixtures_verified: false,
    execution_authorized: false, canonical_execution_committed: false, business_coverage_verified: false, baseline_restored: false,
    automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
}
export async function verifyFixtureRecipe(value: unknown, saved: RunPlanArchive, command: string, record: string): Promise<FixtureRecipeView> {
  const v = value as FixtureRecipeView, a = v?.archive, p = saved.artifact.plan
  exactKeys(v, ['metadata', 'archive', 'historical_not_live'])
  exactKeys(a, ['schema', 'project_id', 'record_id', 'invocation_id', 'actor_id', 'recorded_at', 'request', 'parents', 'fixture_digest'])
  exactKeys(a.request, ['project_id', 'run_plan_id', 'run_plan_artifact_hash', 'manifest'])
  const input = await fixtureRecipeRequest(saved, a.request.manifest)
  requireRunPlan(new TextEncoder().encode(serialized(a)).length <= fixtureLimits.bytes + 16384
    && a.schema === 'nasus.http-fixture-recipe.v1' && a.project_id === input.project_id && a.invocation_id === command
    && a.record_id === record && record === await fixtureRecipeIdentity(command) && identity(a.actor_id) && utc(a.recorded_at)
    && v.historical_not_live === true && generationEqual(input, a.request) && generationEqual(a.parents, {
      plan_digest: p.plan_digest, image_revision_id: p.source_pin.image_revision_id, image_artifact_hash: p.source_pin.image_artifact_hash,
      manifest_id: p.source_pin.manifest_id, manifest_hash: p.source_pin.manifest_hash })
    && a.fixture_digest === await canonicalDigest(p.selection.fixtures.find((item) => item.case_id === input.manifest.case_id)))
  requireRunPlan(generationEqual(v.metadata, await expectedFixtureMetadata(a)))
  return v
}
