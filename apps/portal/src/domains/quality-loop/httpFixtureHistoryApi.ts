import { request } from '../../shared/api/client'
import { generationEqual } from './testDesignGenerationValidation'
import { requireRunPlan } from './runPlanValidation'
import { verifyFixtureHistoryItem, verifyFixtureHistoryPage } from './httpFixtureHistoryValidation'
import type { FixtureHistoryItem, FixtureHistoryQuery } from './types/httpFixtureHistory'

const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/quality/http-fixture-operations`
export const fixtureHistoryApi = {
  async page(projectId: string, afterId: string, signal: AbortSignal) {
    const input: FixtureHistoryQuery = { project_id: projectId, after_id: afterId, limit: 3 }
    const value = await request<unknown>(`${root(projectId)}?${new URLSearchParams({ after_id: afterId, limit: '3' })}`, { signal, cache: 'no-store' })
    signal.throwIfAborted(); return verifyFixtureHistoryPage(value, input)
  },
  async read(projectId: string, selected: FixtureHistoryItem, signal: AbortSignal) {
    verifyFixtureHistoryItem(selected, projectId)
    const value = await request<unknown>(`${root(projectId)}/${encodeURIComponent(selected.invocation_id)}`, { signal, cache: 'no-store' })
    signal.throwIfAborted()
    const item = verifyFixtureHistoryItem(value, projectId)
    // Status/confirmation transitions require an explicit fresh inventory, never rebinding old selection.
    requireRunPlan(generationEqual(item, selected)); return item
  },
}
