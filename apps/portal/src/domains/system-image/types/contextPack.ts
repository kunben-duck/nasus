import type { ObservableOracle } from '../../quality-loop/acceptanceSpecificationApi'
import type { LinkCandidateEndpoint } from '../linkCandidateApi'
import type { SystemImageData } from './data'

export interface ContextSelection { project_id: string; image_revision_id: string; image_artifact_hash: string }
export type ContextPolicy = 'nasus.test-design-context.v1' | 'nasus.test-design-context.v2' | 'nasus.test-design-context.v3' | 'nasus.test-design-context.v4' | 'nasus.test-design-context.v5'
export interface ContextRequest extends ContextSelection {
  purpose: 'test_design'; policy_revision: ContextPolicy; max_tokens: number; candidate_limit: number
  publication_id?: string
  retrieval_bindings?: Record<string, string>
}
export interface ContextConstraint {
  object_id: string; source_revision_id: string; document_revision_id: string; evidence_ids: string[]
  source_fields: { name: string; value: string; start_line: number; end_line: number; snippet_hash: string }[]
  authority: { object_id: string; revision_id: string | null; artifact_hash: string | null; status: 'approved' | 'withdrawn' | 'unapproved' }
  oracle: ObservableOracle | null; semantic_class: 'expected' | 'pending_confirmation'
  kind?: 'acceptance_criterion' | 'business_rule'
}
export interface TestDesignContext extends ContextSelection {
  schema_version: 'nasus.context-pack.v1' | 'nasus.context-bundle.v1'; purpose: 'test_design'; policy_version: ContextPolicy
  source_manifest_id: string; source_manifest_hash: string
  publication_pin?: NonNullable<NonNullable<SystemImageData['read_state']>['pin']>
  required_constraints: ContextConstraint[]
  facts: { target_object_id: string; relation: 'implements' | 'asserts'; endpoint: LinkCandidateEndpoint
    review_status: string; semantic_class: 'retrieval_candidate_not_coverage' }[]
  readiness: { status: 'partial' | 'blocked'; reason_codes: string[] }
  use_policy: 'draft_investigation_only_not_generation_or_execution_authorization'
  retrieval: { method: 'nasus.link-recall.reviewed.v2' | 'nasus.link-recall.indexed-reviewed.v3'; fallback_used: boolean; truncated: boolean }
  conflicts: { status: 'not_evaluated' }
  budget: { max_tokens: number; measure: 'utf8_bytes_upper_bound_not_provider_token_count'; used_upper_bound: number; omitted_optional_facts: number
    scope?: 'per_part'; total_upper_bound?: number; part_count?: number }
  partition?: { target_object_ids: string[]; global_constraint_ids: string[]; rule_inheritance: 'all_source_business_rules' }
  parts?: { part_id: string; context: TestDesignContext }[]
}
export interface ContextPreview { request: ContextRequest; input_digest: string; context: TestDesignContext }
export interface ContextMetadata extends ContextSelection {
  context_id: string; input_digest: string; invocation_id: string; actor_id: string; recorded_at: string
  policy_revision: ContextPolicy; artifact_hash: string; content_hash: string
  purpose: 'test_design'; readiness: 'partial' | 'blocked'; mandatory_count: number
}
export interface ContextArchive {
  metadata: ContextMetadata; context: TestDesignContext
  derivation: { request: ContextRequest & { expected_input_digest: string }; input_digest: string; historical_not_live: true }
  current_use: { stale: boolean; generation_authorized: false; reason: 'inputs_changed' | 'draft_investigation_only' | 'current_mandatory_context_over_budget' | 'published_image_head_changed' | 'retrieval_model_configuration_changed' | 'source_change_invalidated'; invalidation_id?: string }
}
export interface ContextHistory {
  request: ContextSelection & { limit: number; after_id: string }; items: ContextMetadata[]; next_after_id: string | null
}
