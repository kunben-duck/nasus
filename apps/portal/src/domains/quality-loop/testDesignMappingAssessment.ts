import type { GenerationArchive } from './types/testDesignGeneration'
import type { AssertionReview, MappingAssessment } from './types/testDesignMapping'
import { compareMappingIds } from './testDesignMappingPartitions'

type Decision = Pick<AssertionReview, 'case_id' | 'row_id' | 'decision'>
export function assessmentFromDecisions(draft: GenerationArchive, values: Decision[]): MappingAssessment {
  const byRow = new Map<string, Decision[]>()
  for (const value of values) {
    const group = byRow.get(value.row_id) ?? []
    group.push(value); byRow.set(value.row_id, group)
  }
  const original = draft.result.proposal.coverage
  const rows = original.rows.map((row) => {
    const decisions = byRow.get(row.row_id) ?? []
    const accepted = decisions.filter((item) => item.decision === 'accept').map((item) => item.case_id).sort(compareMappingIds)
    return { ...row, mapping_status: 'reviewed' as const, assertion_mapped: !!accepted.length,
      accepted_case_ids: accepted, rejected_case_ids: decisions.filter((item) => item.decision === 'reject').map((item) => item.case_id).sort(compareMappingIds),
      deferred_case_ids: decisions.filter((item) => item.decision === 'defer').map((item) => item.case_id).sort(compareMappingIds),
      automated: false as const, executed_on_target: false as const, passed: false as const, unknown: true as const }
  })
  const decisions = new Map(values.map((item) => [JSON.stringify([item.case_id, item.row_id]), item.decision]))
  return { coverage: { ...original, schema: 'nasus.reviewed-test-design-coverage.v1', rows,
      assertion_mapped_count: rows.filter((row) => row.assertion_mapped).length, automated_count: 0, executed_on_target_count: 0,
      passed_count: 0, unknown_count: rows.length, execution_authorized: false },
    accepted_case_ids: draft.result.proposal.cases.filter((item) => item.assertions.every((a) => decisions.get(JSON.stringify([item.case_id, a.row_id])) === 'accept')).map((item) => item.case_id).sort(compareMappingIds),
    accepted_assertion_count: values.filter((item) => item.decision === 'accept').length,
    rejected_assertion_count: values.filter((item) => item.decision === 'reject').length,
    deferred_assertion_count: values.filter((item) => item.decision === 'defer').length,
    mapping_complete: !!rows.length && rows.every((row) => row.assertion_mapped && !row.gap_ids.length), execution_authorized: false }
}
