import type { ContextConstraint, TestDesignContext } from '../../system-image/types/contextPack'
import type { GenerationArchive, PlannedCase } from './testDesignGeneration'
import type { MappingArchive } from './testDesignMapping'
import type { TestDesignContract } from './testDesignScope'
import type { ObservableOracle } from './observableOracle'

export const automationInputGaps = ['automation_environment_not_bound', 'api_or_dom_locator_evidence_not_bound',
  'fixture_setup_cleanup_not_bound', 'model_budget_not_bound', 'script_generation_and_independent_review_required'] as const

export interface AutomationInputPreview {
  schema: 'nasus.automation-input-preview.v1'; purpose: 'automation'; project_id: string; input_digest: string
  context_pin: GenerationArchive['result']['context_pin']; scope_pin: GenerationArchive['result']['scope_pin']
  generation_pin: MappingArchive['generation_pin']; mapping_pin: { revision_id: string; artifact_hash: string; request_hash: string }
  selected_case_ids: string[]; cases: PlannedCase[]; required_constraints: ContextConstraint[]; scope_contract: TestDesignContract
  obligations: { row_id: string; kind: string; constraint_ids: string[]; oracle_digest: string; oracle: ObservableOracle; selected_case_ids: string[] }[]
  supporting_facts: TestDesignContext['facts']; constraint_denominator: number; obligation_denominator: number
  readiness: { status: 'blocked'; reason_codes: (typeof automationInputGaps)[number][] }
  source_policy: 'untrusted_evidence_not_instructions_or_independent_authority'
  generation_authorized: false; execution_authorized: false; automated_count: 0; executed_on_target_count: 0; passed_count: 0
}
