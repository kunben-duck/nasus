import type { CaseExecutionHistory, CaseExecutionRow } from './types/runPlanCaseJobs'
import type { RunPlanValue } from './types/runPlans'

const records = (value: unknown): Record<string, unknown>[] => Array.isArray(value)
  ? value.filter((item): item is Record<string, unknown> => item !== null && typeof item === 'object' && !Array.isArray(item)) : []

export function summarizeCaseObservations(plan: RunPlanValue, history: NonNullable<CaseExecutionHistory['history']>) {
  const counts: Record<CaseExecutionRow['status'], number> = {
    passed: 0, failed: 0, error: 0, timed_out: 0, outcome_unknown: 0, not_dispatched: 0,
  }
  const prepared = new Map(plan.prepared.cases.map((item) => [item.case_id, item]))
  const scripts = new Map(plan.proposal.scripts.map((item) => [item.case_id, item]))
  const observations = new Map(history.observations.map((item) => [item.case_id, item]))
  const cases = history.state.cases.map((row) => {
    counts[row.status]++
    const planned = prepared.get(row.case_id), script = scripts.get(row.case_id), result = observations.get(row.case_id)
    const receipt = result?.runner_receipt as Record<string, unknown> | undefined
    const responses = new Map<string, number>()
    for (const response of records(receipt?.requests)) {
      const index = response.step_index, status = response.response_status
      const action = typeof index === 'number' ? script?.actions[index] : undefined
      if (action?.action === 'request' && typeof action.request_id === 'string' && action.request_id === response.request_id
        && action.method === response.method && typeof status === 'number' && Number.isInteger(status) && status >= 100 && status <= 599) {
        responses.set(action.request_id, status)
      }
    }
    const assertions = new Map(script?.assertions.map((item) => [item.row_id, item]))
    const oracles = records(result?.oracles).flatMap((observed) => {
      const original = typeof observed.row_id === 'string' ? assertions.get(observed.row_id) : undefined
      if (!original || typeof observed.status !== 'string') return []
      const action = script?.actions[original.action_index]
      const responseStatus = typeof action?.request_id === 'string' ? responses.get(action.request_id) : undefined
      return [{ id: original.row_id, status: observed.status, step: original.source_step_index + 1,
        expected: original.oracle.expected_result, responseStatus }]
    })
    return { id: row.case_id, title: planned?.title || row.case_id, status: row.status, oracles }
  })
  return { counts, cases }
}
