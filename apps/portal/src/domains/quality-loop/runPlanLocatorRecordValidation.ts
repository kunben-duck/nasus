import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import { exactKeys, identity, originalObservationIdentity, utc } from './environmentRecordValidation'
import { locatorQuery, verifyRunPlanLocators } from './runPlanLocatorValidation'
import type { RunPlanArchive } from './types/runPlans'
import type { LocatorRecordArchive, LocatorRecordMetadata, LocatorRecordView } from './types/runPlanLocatorRecords'

export const locatorRecordIdentity = (command: string) => originalObservationIdentity(command, 'nasus:run-plan-locators:')
export async function expectedLocatorRecordMetadata(a: LocatorRecordArchive): Promise<LocatorRecordMetadata> {
  return { schema: a.schema, record_id: a.record_id, invocation_id: a.invocation_id, actor_id: a.actor_id, recorded_at: a.recorded_at,
    ...a.request, ...a.parents, request_hash: await canonicalDigest(a.request), artifact_hash: await canonicalDigest(a),
    inventory_hash: a.report.inventory.inventory_hash, report_hash: a.report.report_hash, summary: a.report.summary, status: 'recorded',
    historical_not_live: true, source_bytes_verified: true, durable_locator_evidence_verified: true,
    runtime_locators_verified: false, fixtures_verified: false, execution_authorized: false, business_coverage_verified: false,
    automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
}
export async function verifyLocatorRecord(value: unknown, saved: RunPlanArchive, command: string, record: string): Promise<LocatorRecordView> {
  const v = value as LocatorRecordView, a = v?.archive, plan = saved.artifact.plan
  exactKeys(v, ['metadata', 'archive', 'historical_not_live'])
  exactKeys(a, ['schema', 'project_id', 'record_id', 'invocation_id', 'actor_id', 'recorded_at', 'request', 'parents', 'report'])
  requireRunPlan(new TextEncoder().encode(JSON.stringify(a)).length <= 4 * 1024 * 1024 + 32768
    && a.schema === 'nasus.run-plan-locator-record.v1' && a.project_id === saved.metadata.project_id
    && a.invocation_id === command && a.record_id === record && record === await locatorRecordIdentity(command)
    && identity(a.actor_id) && utc(a.recorded_at) && v.historical_not_live === true
    && generationEqual(a.request, locatorQuery(saved)) && generationEqual(a.parents, {
      plan_digest: plan.plan_digest, image_revision_id: plan.source_pin.image_revision_id,
      image_artifact_hash: plan.source_pin.image_artifact_hash, manifest_id: plan.source_pin.manifest_id, manifest_hash: plan.source_pin.manifest_hash }))
  // The old query remains a static observation, not an independently committed fact.
  const receipt = { schema: 'nasus.run-plan-locator-receipt.v1', query: a.request, policy: a.report.policy,
    plan_digest: a.parents.plan_digest, image_revision_id: a.parents.image_revision_id, image_artifact_hash: a.parents.image_artifact_hash,
    inventory_hash: a.report.inventory.inventory_hash, report_hash: a.report.report_hash, summary: a.report.summary,
    historical_not_live: true, durable_locator_evidence_verified: false, runtime_locators_verified: false,
    fixtures_verified: false, execution_authorized: false, business_coverage_verified: false,
    automated_count: 0, executed_on_target_count: 0, passed_count: 0 }
  await verifyRunPlanLocators({ receipt, report: a.report }, saved)
  requireRunPlan(generationEqual(v.metadata, await expectedLocatorRecordMetadata(a)))
  return v
}
