import type { CodeFileAnalysis, CodeStructureFact } from '../../system-image/types/codeAnalysis'
import type { RunPlanValue } from './runPlans'

export type LocatorStatus = 'static_match' | 'ambiguous' | 'unresolved' | 'not_found' | 'unsupported'
export interface LocatorSummary extends Record<LocatorStatus, number> { locator_count: number }
export interface LocatorQuery { project_id: string; run_plan_id: string; run_plan_artifact_hash: string }
export type LocatorPolicy = 'nasus.http-locator-static-match.v1' | 'nasus.http-locator-static-match.v2'
export interface FrozenRouteFact extends CodeStructureFact {
  unresolved_match_scope?: { method: string; route_path: string }[] | null
}
export interface FrozenRouteSource {
  pin: { project_id: string; image_revision_id: string; image_artifact_hash: string; manifest_id: string; manifest_hash: string
    binding_id: string; source_revision_id: string; source_id: string; external_revision: string; content_hash: string; snapshot_manifest_hash: string }
  files: CodeFileAnalysis[]; routes: FrozenRouteFact[]
}
export interface LocatorCandidate extends FrozenRouteFact { binding_id: string; source_revision_id: string; snapshot_manifest_hash: string }
export interface ActionLocator {
  case_id: string; action_index: number; action_digest: string; source_step_indices: number[]
  candidates: LocatorCandidate[]; status: LocatorStatus; reason: string; request_id?: string; method?: string; path?: string
}
export interface StaticLocatorAuthority {
  runtime_locators_verified: false; fixtures_verified: false; execution_authorized: false; business_coverage_verified: false
  automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
export interface RunPlanLocatorView {
  receipt: StaticLocatorAuthority & {
    schema: 'nasus.run-plan-locator-receipt.v1'; query: LocatorQuery; policy: LocatorPolicy
    plan_digest: string; image_revision_id: string; image_artifact_hash: string; inventory_hash: string; report_hash: string
    summary: LocatorSummary; historical_not_live: true; durable_locator_evidence_verified: false
  }
  report: StaticLocatorAuthority & {
    schema: 'nasus.run-plan-http-locators.v1' | 'nasus.run-plan-http-locators.v2'; policy: LocatorPolicy; project_id: string; plan_digest: string
    script_pin: RunPlanValue['script_pin']; source_pin: RunPlanValue['source_pin']; locators: ActionLocator[]; summary: LocatorSummary
    scope: 'fixed_source_static_method_and_path_only'; report_hash: string
    inventory: { schema: 'nasus.frozen-http-route-inventory.v1' | 'nasus.frozen-http-route-inventory.v2'
      rule: 'java.import-resolved-http-locators.v1' | 'java.import-resolved-http-locators.v2'
      provider: string; provider_version: string; sources: FrozenRouteSource[]; inventory_hash: string }
  }
}
