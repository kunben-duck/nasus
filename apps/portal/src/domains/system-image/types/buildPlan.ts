export interface BuildTarget {
  project_id: string
  target_baseline_id: string
  target_version_id: string | null
  expected_head_id: string | null
  expected_head_hash: string | null
}

export interface BuildPlanInput {
  project_id: string
  source_manifest_id: string
  objective: string
  mode: 'initialize' | 'enrich' | 'refresh' | 'repair'
  purpose: 'structure' | 'behavior' | 'traceability'
  budget: { max_tool_calls: number; max_model_calls: number; max_active_seconds: number; max_cost_microusd: number | null }
  target?: BuildTarget
}

export interface BuildPlanRevision {
  revision_hash: string
  revision: {
    revision_id: string; project_id: string; goal_id: string; root_plan_id: string
    from_plan_id: string; from_plan_digest: string; plan_id: string; plan_digest: string
    source_manifest_id: string; source_manifest_hash: string; revision_number: number
    parent_revision_id: string | null; parent_revision_hash: string | null
    invocation_id: string; created_at: string; execution_authorized: false; publication_authorized: false
  }
}

export interface BuildPlanSummary {
  plan_id: string; plan_digest: string; created_at: string; source_manifest_id: string
  state: 'draft'; purpose: BuildPlanInput['purpose']; work_item_count: number
}

export interface BuildExecutionConsent {
  authorization_id: string; goal_id: string; target_baseline_id: string; target_version_id: string | null
  confirmed_at: string
  budget: { max_tool_calls: number; max_model_calls: number; max_active_seconds: number; max_cost_microusd: number }
  work_item_ids: string[]; reserved_work_item_ids: string[]; unapproved_work_item_ids: string[]
  publication_allowed: false
}

export interface BuildPlan {
  plan_id: string; project_id: string; plan_digest: string; created_at: string
  structural_artifacts: { invocation_id: string; image_revision_id: string; target_baseline_id: string; confirmed_at: string }[]
  execution_authorizations?: BuildExecutionConsent[]
  proposal: {
    intent: BuildPlanInput & {
      source_manifest_hash: string
      sources: { binding_id: string; source_type: string; source_revision_id: string | null; status: string }[]
      scope_binding_ids?: string[]
      expected_head?: string | null
      expected_head_status?: 'unresolved' | 'resolved'
    }
    policy_version?: string
    state: 'draft'; authorization_state: 'not_granted'; execution_ready: false
    work_items: {
      work_item_id: string; question: string; reason: string; capability: string; proposed_tool_id: string | null
      binding_state: string; dependency_ids: string[]; output_artifact: string; acceptance_conditions: string[]
    }[]
    gaps: { code: string; blocks: string; reason: string; required_action: string }[]
    completion_conditions: string[]
  }
}
