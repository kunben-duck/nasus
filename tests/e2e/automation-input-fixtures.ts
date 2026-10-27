import { canonicalDigest } from '../../apps/portal/src/shared/utils/canonicalDigest'
import { compareMappingIds } from '../../apps/portal/src/domains/quality-loop/testDesignMappingPartitions'
import { automationInputGaps, type AutomationInputPreview } from '../../apps/portal/src/domains/quality-loop/types/automationInput'
import type { GenerationArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'
import type { MappingArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignMapping'
import type { TestDesignContext } from '../../apps/portal/src/domains/system-image/types/contextPack'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'

// Transport specimen only. Actual PG/private MinIO automation inputs have their own API tests.
export async function automationInputFixture(draft: GenerationArchive, mapping: MappingArchive, context: TestDesignContext, scope: ScopeArchive) {
  const selected = [...mapping.assessment!.accepted_case_ids].sort(compareMappingIds)
  const body: Omit<AutomationInputPreview, 'input_digest'> = {
    schema: 'nasus.automation-input-preview.v1', purpose: 'automation', project_id: draft.metadata.project_id,
    context_pin: draft.result.context_pin, scope_pin: draft.result.scope_pin, generation_pin: mapping.generation_pin,
    mapping_pin: { revision_id: mapping.revision.revision_id, artifact_hash: mapping.revision.artifact_hash, request_hash: mapping.revision.request_hash },
    selected_case_ids: selected, cases: draft.result.proposal.cases.filter((item) => selected.includes(item.case_id))
      .sort((a, b) => compareMappingIds(a.case_id, b.case_id)),
    required_constraints: context.required_constraints, scope_contract: scope.request.contract!, supporting_facts: context.facts,
    constraint_denominator: mapping.assessment!.coverage.constraint_denominator,
    obligation_denominator: mapping.assessment!.coverage.obligation_denominator,
    obligations: mapping.assessment!.coverage.rows.map((row) => ({ row_id: row.row_id, kind: row.kind,
      constraint_ids: row.constraint_ids, oracle_digest: row.oracle_digest,
      oracle: draft.result.proposal.cases.flatMap((item) => item.assertions).find((item) => item.row_id === row.row_id)!.oracle,
      selected_case_ids: row.accepted_case_ids.filter((id) => selected.includes(id)).sort(compareMappingIds) })),
    readiness: { status: 'blocked', reason_codes: [...automationInputGaps] },
    source_policy: 'untrusted_evidence_not_instructions_or_independent_authority',
    generation_authorized: false, execution_authorized: false, automated_count: 0, executed_on_target_count: 0, passed_count: 0,
  }
  return structuredClone({ ...body, input_digest: await canonicalDigest(body) })
}
