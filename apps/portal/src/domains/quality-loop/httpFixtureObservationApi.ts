import { request } from '../../shared/api/client'
import { verifyFixtureOriginalObservation } from './httpFixtureObservationValidation'
import { verifyFixtureHistoryItem } from './httpFixtureHistoryValidation'
import { generationDigest } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import type { FixtureHistoryItem } from './types/httpFixtureHistory'

export const fixtureObservationApi = {
  async read(item: FixtureHistoryItem, sourceScopeDigest: string, signal: AbortSignal) {
    verifyFixtureHistoryItem(item, item.project_id)
    requireRunPlan(generationDigest(sourceScopeDigest))
    signal.throwIfAborted()
    const value = await request<unknown>(`/v1/projects/${encodeURIComponent(item.project_id)}/quality/http-fixture-operations/${encodeURIComponent(item.invocation_id)}/observation`,
      { signal, cache: 'no-store' })
    const result = await verifyFixtureOriginalObservation(value, item, sourceScopeDigest)
    signal.throwIfAborted(); return result
  },
}
