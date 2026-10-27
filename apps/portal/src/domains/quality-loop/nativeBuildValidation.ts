import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { verifyNativeBuild } from './runPlanBuildValidation'
import type { FrozenImageSources } from '../system-image/frozenImageSources'
import type { NativeBuildCommand, NativeBuildJobView, NativeBuildPreview, NativeBuildSelection } from './types/nativeBuilds'

export const nativeSelectionKeys = ['project_id', 'image_revision_id', 'image_artifact_hash', 'binding_id', 'source_revision_id', 'artifact_path', 'expected_artifact_hash'] as const
export const nativeCommandKeys = [...nativeSelectionKeys, 'request_digest', 'operator_policy_digest', 'source_scope_digest'] as const
export function requireNativeBuild(condition: unknown): asserts condition { if (!condition) throw new Error('Original native build could not be verified') }
export function nativeArtifactPath(value: unknown): value is string {
  return typeof value === 'string' && new TextEncoder().encode(value).length <= 1024 && /^target\/(?:[^/]+\/)*[^/]+\.jar$/.test(value)
    && !value.includes('\\') && [...value].every((char) => char.charCodeAt(0) >= 32)
    && !value.split('/').some((part) => ['.', '..', '.git'].includes(part))
}
export function requireNativeSelection(value: NativeBuildSelection, sources: FrozenImageSources) {
  requireNativeBuild(value && [value.project_id, value.image_revision_id, value.binding_id, value.source_revision_id].every(scriptId)
    && generationDigest(value.image_artifact_hash) && nativeArtifactPath(value.artifact_path)
    && (value.expected_artifact_hash === null || generationDigest(value.expected_artifact_hash))
    && value.project_id === sources.project_id && value.image_revision_id === sources.image_revision_id && value.image_artifact_hash === sources.image_artifact_hash
    && sources.source_members.some((s) => s.source_type === 'code' && s.status === 'captured' && s.binding_id === value.binding_id && s.source_revision_id === value.source_revision_id))
}
export function requireNativeCommand(value: NativeBuildCommand, sources: FrozenImageSources) {
  requireNativeSelection(value, sources)
  requireNativeBuild(['request_digest', 'operator_policy_digest', 'source_scope_digest'].every((key) => generationDigest(value[key as keyof NativeBuildCommand])))
}
function requireSourcePin(pin: NativeBuildPreview['source']['pin'], input: NativeBuildSelection, sources: FrozenImageSources) {
  requireNativeBuild(pin && ['project_id', 'image_revision_id', 'image_artifact_hash', 'binding_id', 'source_revision_id'].every((key) => pin[key] === input[key as keyof NativeBuildSelection])
    && pin.manifest_id === sources.manifest_id && pin.manifest_hash === sources.manifest_hash
    && scriptId(pin.source_id) && scriptId(pin.external_revision) && generationDigest(pin.content_hash) && generationDigest(pin.snapshot_manifest_hash))
}
export async function verifyNativePreview(value: unknown, selection: NativeBuildSelection, sources: FrozenImageSources): Promise<NativeBuildPreview> {
  const v = value as NativeBuildPreview, p = v?.operator_policy
  requireNativeCommand(v?.request, sources)
  requireNativeBuild(nativeSelectionKeys.every((key) => generationEqual(v.request[key], selection[key]))
    && Object.keys(v.request).length === nativeCommandKeys.length && v.status === 'preview' && v.source_execution_started === false && v.execution_authorized === false
    && Number.isSafeInteger(v.source?.file_count) && v.source.file_count > 0 && v.source.file_count <= 1000
    && Number.isSafeInteger(v.source.byte_count) && v.source.byte_count >= 0 && v.source.byte_count <= 32 * 1024 * 1024
    && p?.adapter === 'nasus.offline-java21-maven3911.v1' && generationDigest(p.image_id) && generationDigest(p.cache_identity_hash)
    && Number.isSafeInteger(p.timeout_seconds) && p.timeout_seconds > 0 && p.timeout_seconds <= 300 && p.network === 'none'
    && p.cache_access === 'read_only' && p.cache_contents_attested === false && await canonicalDigest(p) === v.request.operator_policy_digest
    && generationEqual(v.remaining_gates, ['independent_build_confirmation', 'native_target_execution']))
  requireSourcePin(v.source.pin, selection, sources)
  return v
}
export async function verifyNativeJob(value: unknown, input: NativeBuildCommand, invocation: string, status: string, sources: FrozenImageSources): Promise<NativeBuildJobView> {
  requireNativeCommand(input, sources)
  const v = value as NativeBuildJobView
  requireNativeBuild(v && v.project_id === input.project_id && v.invocation_id === invocation && v.status === status && v.execution_authorized === false)
  if (v.metadata === null) {
    requireNativeBuild(status !== 'completed' && typeof v.call_reserved === 'boolean' && typeof v.outcome_unknown === 'boolean'
      && ['none', 'active', 'expired'].includes(v.worker) && v.cleanup_confirmed === false
      && v.outcome_unknown === (v.call_reserved && v.worker !== 'active'))
    return v
  }
  const complete = await verifyNativeBuild(value, input.project_id, invocation), r = complete.receipt
  requireSourcePin(r.source.pin, input, sources)
  requireNativeBuild(r.request_digest === input.request_digest && r.artifact.path === input.artifact_path
    && (input.expected_artifact_hash === null || r.artifact.content_hash === input.expected_artifact_hash)
    && await canonicalDigest({ source: r.source, artifact_path: input.artifact_path, expected_artifact_hash: input.expected_artifact_hash, adapter: r.adapter }) === input.request_digest
    && generationDigest(r.toolchain.image_id) && generationDigest(r.toolchain.version_output_hash)
    && r.source.files.some((f) => f.path === 'pom.xml') && r.artifact.byte_count <= 128 * 1024 * 1024
    && !r.source.files.some((f) => f.path === input.artifact_path))
  return complete
}
