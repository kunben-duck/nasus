import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { requireRunPlan, runPlanArtifactSchema } from './runPlanValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { NativeBuildView, RunPlanBuildArchive, RunPlanBuildPreview, RunPlanBuildRequest, RunPlanBuildSelection, RunPlanBuildValue } from './types/runPlanBuilds'

export const buildSelectionKeys = ['project_id', 'run_plan_id', 'run_plan_artifact_hash', 'native_builds', 'target_build_invocation_id', 'reason', 'policy_revision'] as const
export const buildRequestKeys = [...buildSelectionKeys, 'binding_digest', 'source_scope_digest'] as const
export function bindingSelection(value: RunPlanBuildRequest): RunPlanBuildSelection {
  return Object.fromEntries(buildSelectionKeys.map((key) => [key, value[key]])) as unknown as RunPlanBuildSelection
}
export async function verifyNativeBuild(value: unknown, project: string, invocation: string): Promise<NativeBuildView> {
  const v = value as NativeBuildView, m = v?.metadata, r = v?.receipt
  requireRunPlan(v?.project_id === project && v.invocation_id === invocation && m && r && m.project_id === project
    && m.invocation_id === invocation && scriptId(m.build_id) && generationDigest(m.artifact_hash) && generationDigest(m.receipt_digest)
    && await canonicalDigest(r) === m.receipt_digest && generationDigest(r.request_digest) && m.request_digest === r.request_digest
    && r.schema === 'nasus.native-build.v1' && r.adapter === 'nasus.offline-java21-maven3911.v1'
    && r.native_build_verified === true && r.execution_authorized === false && m.execution_authorized === false
    && v.execution_authorized === false && r.executed_on_target_count === 0 && r.passed_count === 0
    && r.reproducible_build_verified === false && r.dependency_supply_chain_verified === false
    && v.historical_not_live === true && generationEqual(m.artifact, r.artifact) && r.source?.file_mode_attested === false
    && Array.isArray(r.source.files) && r.source.files.length > 0 && r.source.files.length <= 1000
    && new Set(r.source.files.map((f) => f.path)).size === r.source.files.length
    && r.source.files.every((f) => typeof f.path === 'string' && generationDigest(f.content_hash) && Number.isSafeInteger(f.byte_count) && f.byte_count >= 0)
    && generationDigest(r.artifact?.content_hash) && Number.isSafeInteger(r.artifact.byte_count) && r.artifact.byte_count > 0
    && /^target\/(?:[^/]+\/)*[^/]+\.jar$/.test(r.artifact.path) && !r.artifact.path.split('/').some((p) => p === '.' || p === '..')
    && r.toolchain?.java === '21' && r.toolchain.maven === '3.9.11' && r.toolchain.network === 'none'
    && r.toolchain.dependency_cache === 'operator_read_only')
  return v
}
export function originalCodeSources(plan: RunPlanArchive) {
  return plan.artifact.plan.source_pin.source_members.filter((s) => s.source_type === 'code' && s.status === 'captured')
}
export function buildSelection(plan: RunPlanArchive, builds: NativeBuildView[], target: string, reason: string): RunPlanBuildSelection {
  requireRunPlan(reason.trim().length > 0 && reason.length <= 4096 && scriptId(target))
  return { project_id: plan.metadata.project_id, run_plan_id: plan.metadata.run_plan_id, run_plan_artifact_hash: plan.metadata.artifact_hash,
    native_builds: builds.map(({ metadata: m }) => ({ invocation_id: m.invocation_id, build_id: m.build_id, receipt_digest: m.receipt_digest, artifact_hash: m.artifact_hash })),
    target_build_invocation_id: target, reason: reason.trim(), policy_revision: 'nasus.run-plan-build.v1' }
}
// Match Python's complete JSON byte budget, including its separator spaces.
function budgetJson(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(budgetJson).join(', ') + ']'
  if (value !== null && typeof value === 'object') return '{' + Object.entries(value).map(([k, v]) => JSON.stringify(k) + ': ' + budgetJson(v)).join(', ') + '}'
  return JSON.stringify(value)
}
export async function expectedBuildBinding(plan: RunPlanArchive, selection: RunPlanBuildSelection, builds: NativeBuildView[]): Promise<RunPlanBuildValue> {
  const source = plan.artifact.plan.source_pin, expected = originalCodeSources(plan), declared = plan.artifact.plan.selection.target_build
  const { plan_digest: originalDigest, ...unsigned } = plan.artifact.plan
  requireRunPlan(selection.project_id === plan.metadata.project_id && selection.run_plan_id === plan.metadata.run_plan_id
    && selection.run_plan_artifact_hash === plan.metadata.artifact_hash && await canonicalDigest(plan.artifact) === plan.metadata.artifact_hash
    && ['nasus.run-plan.v1', 'nasus.run-plan.v2', 'nasus.run-plan.v3'].includes(plan.artifact.plan.schema)
    && plan.artifact.plan.schema === plan.artifact.plan.selection.policy_revision
    && plan.artifact.schema === runPlanArtifactSchema(plan.artifact.plan.schema)
    && plan.artifact.plan.status === 'prepared'
    && plan.artifact.plan.execution_authorized === false && plan.artifact.plan.automated_count === 0
    && plan.artifact.plan.executed_on_target_count === 0 && plan.artifact.plan.passed_count === 0 && await canonicalDigest(unsigned) === originalDigest
    && selection.policy_revision === 'nasus.run-plan-build.v1' && selection.reason.trim().length > 0 && selection.reason.length <= 4096
    && expected.length > 0 && expected.length <= 1000 && builds.length === expected.length && selection.native_builds.length === expected.length
    && new Set(selection.native_builds.map((b) => b.invocation_id)).size === expected.length
    && new Set(selection.native_builds.map((b) => b.build_id)).size === expected.length
    && declared.code_sources.length === expected.length && expected.every((s) => declared.code_sources.some((c) => c.binding_id === s.binding_id && c.source_revision_id === s.source_revision_id)))
  const members: RunPlanBuildValue['builds'] = [], observed = new Set<string>()
  for (const build of builds) {
    await verifyNativeBuild(build, selection.project_id, build.invocation_id)
    const r = build.receipt, pin = r.source.pin, ref = selection.native_builds.find((b) => b.invocation_id === build.invocation_id)
    requireRunPlan(ref && ['invocation_id', 'build_id', 'artifact_hash', 'receipt_digest'].every((key) => ref[key as keyof typeof ref] === build.metadata[key])
      && ['project_id', 'image_revision_id', 'image_artifact_hash', 'manifest_id', 'manifest_hash'].every((key) => pin[key] === source[key as keyof typeof source])
      && !observed.has(pin.binding_id) && expected.some((s) => s.binding_id === pin.binding_id && s.source_revision_id === pin.source_revision_id))
    const definitions = r.source.files.filter((f) => f.path === 'pom.xml')
    requireRunPlan(definitions.length === 1); observed.add(pin.binding_id)
    members.push({ ...ref, source_pin: pin, request_digest: r.request_digest, source_files_digest: await canonicalDigest(r.source.files),
      build_definition_hash: definitions[0].content_hash, artifact: r.artifact, toolchain: r.toolchain })
  }
  const target = members.find((b) => b.invocation_id === selection.target_build_invocation_id)
  requireRunPlan(target && target.artifact.path.split('/').at(-1) === declared.artifact_name && target.artifact.content_hash === declared.artifact_hash
    && target.build_definition_hash === declared.build_definition_hash && declared.runtime === 'Java' && declared.runtime_version === '21'
    && declared.build_tool === 'Maven' && declared.build_tool_version === '3.9.11')
  const value = { schema: 'nasus.run-plan-build.v1' as const, project_id: selection.project_id, selection,
    run_plan_id: selection.run_plan_id, run_plan_artifact_hash: selection.run_plan_artifact_hash, plan_digest: plan.artifact.plan.plan_digest,
    source_pin: { project_id: source.project_id, image_revision_id: source.image_revision_id, image_artifact_hash: source.image_artifact_hash,
      manifest_id: source.manifest_id, manifest_hash: source.manifest_hash },
    builds: members.sort((a, b) => a.source_pin.binding_id < b.source_pin.binding_id ? -1 : a.source_pin.binding_id > b.source_pin.binding_id ? 1 : 0),
    target_build_invocation_id: selection.target_build_invocation_id, target_artifact_hash: target.artifact.content_hash,
    native_build_source_attested: true as const, source_file_modes_attested: false as const, execution_authorized: false as const,
    automated_count: 0 as const, executed_on_target_count: 0 as const, passed_count: 0 as const,
    reproducible_build_verified: false as const, dependency_supply_chain_verified: false as const,
    remaining_gates: plan.artifact.plan.remaining_gates.filter((g) => g !== 'native_build_source_attestation') }
  const result = { ...value, binding_digest: await canonicalDigest(value) }
  requireRunPlan(new TextEncoder().encode(budgetJson(result)).length <= 4 * 1024 * 1024)
  return result
}
export async function verifyBuildPreview(value: unknown, plan: RunPlanArchive, selection: RunPlanBuildSelection, builds: NativeBuildView[]): Promise<RunPlanBuildPreview> {
  const v = value as RunPlanBuildPreview, expected = await expectedBuildBinding(plan, selection, builds)
  requireRunPlan(v?.status === 'preview' && v.native_build_source_attested === true && v.execution_authorized === false
    && generationEqual(bindingSelection(v.request), selection) && generationDigest(v.request.source_scope_digest)
    && v.request.binding_digest === expected.binding_digest && v.code_source_count === expected.builds.length
    && v.target_artifact_hash === expected.target_artifact_hash
    && generationEqual(v.remaining_gates, ['independent_build_binding_confirmation', ...expected.remaining_gates]))
  return v
}
export async function verifyBuildArchive(value: unknown, request: RunPlanBuildRequest, commandId: string, plan: RunPlanArchive, builds: NativeBuildView[]): Promise<RunPlanBuildArchive> {
  const v = value as RunPlanBuildArchive, m = v?.metadata, a = v?.artifact
  const expected = await expectedBuildBinding(plan, bindingSelection(request), builds)
  requireRunPlan(a && m && a.schema === 'nasus.run-plan-build-artifact.v1' && generationEqual(a.request, request)
    && generationEqual(a.binding, expected) && request.binding_digest === expected.binding_digest && generationDigest(request.source_scope_digest)
    && scriptId(m.binding_id) && m.invocation_id === commandId && scriptId(m.actor_id) && Number.isFinite(Date.parse(m.recorded_at))
    && ['project_id', 'binding_id', 'invocation_id', 'actor_id', 'recorded_at'].every((k) => a[k as keyof typeof a] === m[k])
    && ['project_id', 'binding_digest', 'run_plan_id', 'run_plan_artifact_hash', 'plan_digest', 'target_artifact_hash'].every((k) => m[k] === expected[k as keyof typeof expected])
    && m.image_revision_id === expected.source_pin.image_revision_id && m.manifest_id === expected.source_pin.manifest_id
    && m.artifact_hash === await canonicalDigest(a) && m.request_hash === await canonicalDigest(request)
    && v.historical_not_live === true && typeof v.current_use?.inputs_current === 'boolean'
    && (!v.current_use.inputs_current || plan.current_use.inputs_current) && v.current_use.native_build_source_attested === true
    && v.current_use.environment_verified === false && v.current_use.fixtures_verified === false && v.current_use.execution_authorized === false)
  return v
}
