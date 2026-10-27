import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { identity } from './environmentRecordValidation'
import { requireRunPlan } from './runPlanValidation'
import type { FixtureHistoryItem, FixtureHistoryPage, FixtureHistoryQuery } from './types/httpFixtureHistory'

const authority = ['execution_authorized', 'canonical_execution_committed', 'business_coverage_verified', 'baseline_restored'] as const
const itemKeys = ['project_id', 'invocation_id', 'tool_id', 'stage', 'status', 'request_digest', 'recipe_id', 'recipe_artifact_hash',
  'run_plan_id', 'run_plan_artifact_hash', 'case_id', 'attempt_id', 'operation', 'original_execution_id', 'grant_id', 'grant_digest', 'observation', ...authority]
const stages = { grant: 'quality.http_fixture.authorize', execute: 'quality.http_fixture.execute', cancel: 'quality.http_fixture.cancel' }
const statuses = ['pending', 'waiting_confirmation', 'waiting_approval', 'running', 'completed', 'failed', 'cancelled']
const observation = 'original_command_metadata_not_target_observation'
function keys(v: object, expected: string[]) {
  return Object.keys(v).length === expected.length && expected.every((key) => Object.hasOwn(v, key))
}
export function verifyFixtureHistoryItem(value: unknown, projectId: string): FixtureHistoryItem {
  const v = value as FixtureHistoryItem
  requireRunPlan(v && typeof v === 'object' && keys(v, itemKeys) && v.project_id === projectId && identity(projectId)
    && [v.invocation_id, v.recipe_id, v.run_plan_id, v.case_id, v.attempt_id].every(identity)
    && [v.request_digest, v.recipe_artifact_hash, v.run_plan_artifact_hash].every(generationDigest)
    && Object.hasOwn(stages, v.stage) && v.tool_id === stages[v.stage] && statuses.includes(v.status)
    && ['setup', 'cleanup'].includes(v.operation) && v.observation === observation && authority.every((key) => v[key] === false))
  requireRunPlan(v.stage === 'grant' ? v.original_execution_id === null && v.grant_id === null && v.grant_digest === null
    : identity(v.original_execution_id) && identity(v.grant_id) && generationDigest(v.grant_digest)
      && (v.stage !== 'execute' || v.original_execution_id === v.invocation_id))
  return v
}
export function verifyFixtureHistoryPage(value: unknown, input: FixtureHistoryQuery): FixtureHistoryPage {
  const v = value as FixtureHistoryPage
  requireRunPlan(identity(input.project_id) && typeof input.after_id === 'string' && input.after_id.length <= 128
    && [...input.after_id].every((char) => char.charCodeAt(0) >= 32 && char.charCodeAt(0) !== 127)
    && Number.isSafeInteger(input.limit) && input.limit >= 1 && input.limit <= 5)
  requireRunPlan(v && typeof v === 'object' && keys(v, ['schema', 'request', 'items', 'total', 'next_after_id', 'source_scope_digest', 'observation', ...authority])
    && v.schema === 'nasus.http-fixture-operation-history.v1' && generationEqual(v.request, input)
    && Array.isArray(v.items) && v.items.length <= input.limit && Number.isSafeInteger(v.total) && v.total >= v.items.length
    && generationDigest(v.source_scope_digest) && v.observation === observation && authority.every((key) => v[key] === false))
  let previous = input.after_id
  for (const item of v.items) {
    verifyFixtureHistoryItem(item, input.project_id)
    requireRunPlan(item.invocation_id > previous); previous = item.invocation_id
  }
  requireRunPlan(v.next_after_id === null || identity(v.next_after_id) && v.items.length === input.limit
    && v.next_after_id === previous && v.total > v.items.length)
  return v
}
export function verifyFixtureHistoryPages(pages: FixtureHistoryPage[], projectId?: string): FixtureHistoryItem[] {
  requireRunPlan(pages.length > 0)
  const first = pages[0], items: FixtureHistoryItem[] = []
  requireRunPlan(projectId === undefined || first.request.project_id === projectId)
  let cursor = ''
  for (const page of pages) {
    verifyFixtureHistoryPage(page, { ...first.request, after_id: cursor })
    requireRunPlan(page.total === first.total && page.source_scope_digest === first.source_scope_digest)
    items.push(...page.items); cursor = page.next_after_id ?? ''
    requireRunPlan(items.length <= first.total)
    if (page !== pages[pages.length - 1]) requireRunPlan(page.next_after_id !== null)
  }
  requireRunPlan(pages[pages.length - 1].next_after_id !== null || items.length === first.total)
  return items
}
