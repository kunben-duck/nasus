import { request } from '../../shared/api/client'
import { locatorQuery, verifyRunPlanLocators } from './runPlanLocatorValidation'
import type { RunPlanArchive } from './types/runPlans'

export async function readRunPlanLocators(plan: RunPlanArchive, signal: AbortSignal) {
  signal.throwIfAborted()
  const input = locatorQuery(plan), params = new URLSearchParams({ run_plan_artifact_hash: input.run_plan_artifact_hash })
  const value = await request<unknown>(`/v1/projects/${encodeURIComponent(input.project_id)}/quality/run-plans/${encodeURIComponent(input.run_plan_id)}/http-locators?${params}`,
    { signal, cache: 'no-store' })
  signal.throwIfAborted()
  const verified = await verifyRunPlanLocators(value, plan)
  signal.throwIfAborted()
  return verified
}
