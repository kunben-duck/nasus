import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest } from './testDesignGenerationValidation'
import { scriptId } from './automationScriptValidation'
import { scriptReason } from './automationScriptReviewValidation'
import { runPlanPolicy } from './runPlanValidation'
import type { ScriptArchive, ScriptReviewArchive } from './types/automationScripts'
import type { RunPlanFields, RunPlanSelection, RunPlanSources } from './types/runPlans'

export function emptyRunPlanFields(draft: ScriptArchive): RunPlanFields {
  return { artifactName: '', artifactHash: '', definitionHash: '', runtime: '', runtimeVersion: '', buildTool: '', buildToolVersion: '',
    environmentId: '', kind: 'test', origin: '', inventoryHash: '', isolation: '', reason: '',
    fixtures: Object.fromEntries(draft.result.prepared.cases.map((item) => [item.case_id, { dataHash: '', setup: '', cleanup: '' }])) }
}
export function runPlanOrigin(value: string) {
  if (!value || value.length > 2048 || /[\s\\]/u.test(value)) return false
  try { const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !!url.hostname && !url.username && !url.password
      && !url.search && !url.hash && url.pathname === '/' && url.port !== '0' && !/[?#@]/u.test(value)
  } catch { return false }
}
const lines = (value: string) => value.split('\n').map((item) => item.trim()).filter(Boolean)
export function runPlanFieldsValid(value: RunPlanFields, draft: ScriptArchive) {
  const cases = draft.result.prepared.cases
  return [value.artifactName, value.runtime, value.runtimeVersion, value.buildTool, value.buildToolVersion, value.environmentId].every((item) => scriptId(item.trim()))
    && [value.artifactHash, value.definitionHash, value.inventoryHash].every(generationDigest)
    && ['local', 'test', 'staging'].includes(value.kind) && runPlanOrigin(value.origin)
    && scriptReason(value.isolation) && scriptReason(value.reason) && cases.length > 0 && cases.length <= 512
    && Object.keys(value.fixtures).length === cases.length && cases.every((item) => {
      const fixture = value.fixtures[item.case_id]
      return fixture && generationDigest(fixture.dataHash) && [fixture.setup, fixture.cleanup].every((text) => {
        const items = lines(text); return items.length > 0 && items.length <= 64 && items.every(scriptReason)
      })
    })
}
export async function runPlanSelection(fields: RunPlanFields, draft: ScriptArchive, review: ScriptReviewArchive, sources: RunPlanSources): Promise<RunPlanSelection> {
  if (!runPlanFieldsValid(fields, draft) || review.revision.status !== 'reviewed' || review.assessment?.review_complete !== true
    || sources.project_id !== draft.metadata.project_id || sources.image_revision_id !== draft.result.prepared.context_pin.image_revision_id
    || sources.image_artifact_hash !== draft.result.prepared.context_pin.image_artifact_hash) throw new Error('Incomplete fixed RunPlan declarations')
  const code_sources = sources.source_members.filter((item) => item.source_type === 'code' && item.status === 'captured')
    .map((item) => { if (!scriptId(item.source_revision_id)) throw new Error('Invalid code revision')
      return { binding_id: item.binding_id, source_revision_id: item.source_revision_id } }).sort((a, b) => a.binding_id.localeCompare(b.binding_id, 'en'))
  if (!code_sources.length) throw new Error('RunPlan requires original code sources')
  const fixtures: RunPlanSelection['fixtures'] = []
  for (const item of draft.result.prepared.cases) { const fixture = fields.fixtures[item.case_id]
    fixtures.push({ case_id: item.case_id, preconditions_digest: await canonicalDigest(item.preconditions), data_manifest_hash: fixture.dataHash,
      setup: lines(fixture.setup), cleanup: lines(fixture.cleanup) }) }
  return { project_id: draft.metadata.project_id, script_revision_id: draft.metadata.script_revision_id, script_artifact_hash: draft.metadata.artifact_hash,
    review_revision_id: review.revision.revision_id, review_artifact_hash: review.revision.artifact_hash,
    target_build: { code_sources, artifact_name: fields.artifactName.trim(), artifact_hash: fields.artifactHash,
      build_definition_hash: fields.definitionHash, runtime: fields.runtime.trim(), runtime_version: fields.runtimeVersion.trim(),
      build_tool: fields.buildTool.trim(), build_tool_version: fields.buildToolVersion.trim() },
    environment: { environment_id: fields.environmentId.trim(), kind: fields.kind, base_url: fields.origin,
      inventory_hash: fields.inventoryHash, isolation: fields.isolation.trim() }, fixtures, reason: fields.reason.trim(), policy_revision: runPlanPolicy(draft) }
}
