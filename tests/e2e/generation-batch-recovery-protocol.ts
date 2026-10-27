import { expect, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { batchJobFixture, type BatchProtocolFixture } from './generation-batch-fixtures'

// Native recovery transport is explicit fixture data; source acquisition,
// publication, scope, accounts and browser rendering use actual isolated PG.
export async function installBatchRecoveryProtocol(page: Page, data: BatchProtocolFixture) {
  const state = { confirmed: false, completed: false, denied: false, corruptOffer: false, writes: [] as object[] }
  const sourceId = data.job.source_invocation_id, recoveryId = data.job.invocation_id
  const offered = data.archive.result.recovery_request!
  const pending = new Map<string, { id: string; tool_id: string; status: string; input_payload: Record<string, unknown> }>()
  await page.route('**/v1/settings/model-configs?route=chat', (route) => route.fulfill({ json: { route: 'chat', configurations: [] } }))
  await page.route('**/quality/test-design-jobs?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    const request = { project_id: data.job.project_id, scope_revision_id: params.get('scope_revision_id'),
      scope_artifact_hash: params.get('scope_artifact_hash'), after_id: params.get('after_id'), limit: Number(params.get('limit')) }
    const items = [{ invocation_id: sourceId, source_invocation_id: sourceId, tool_id: 'quality.test_design.generate', status: 'failed' },
      ...(state.confirmed ? [{ invocation_id: recoveryId, source_invocation_id: sourceId, tool_id: 'quality.test_design.recover',
        status: state.completed ? 'completed' : 'running' }] : [])].sort((a, b) => a.invocation_id.localeCompare(b.invocation_id))
    await route.fulfill({ json: { request, items, next_after_id: null, has_running: state.confirmed && !state.completed,
      generation_authorized: false, execution_authorized: false } })
  })
  await page.route('**/quality/test-design-results/*', (route) => state.denied
    ? route.fulfill({ status: 403, json: { detail: 'Explicit source revocation fixture' } })
    : route.fulfill({ json: data.archive }))
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, row = pending.get(id)
    if (!row) return route.continue()
    row.input_payload.confirmed_by_user = true; row.status = 'running'; state.confirmed = true
    pending.delete(id); await route.fulfill({ json: row })
  })
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const { tool_id: tool, input, idempotency_key: key } = route.request().postDataJSON()
    if (!['query.quality.test_design_job', 'quality.test_design.recover'].includes(tool)) return route.continue()
    expect(key).toBeTruthy()
    if (tool === 'quality.test_design.recover') {
      expect(input).toEqual(offered); expect(state.confirmed).toBe(false)
      const row = { id: recoveryId, tool_id: tool, status: 'waiting_confirmation', input_payload: { ...input } }
      state.writes.push(row); pending.set(row.id, row); return route.fulfill({ json: row })
    }
    if (state.denied) return route.fulfill({ status: 403, json: { detail: 'Explicit source revocation fixture' } })
    expect(input.project_id).toBe(data.job.project_id)
    expect([sourceId, recoveryId]).toContain(input.invocation_id)
    const original = input.invocation_id === sourceId
    const job = batchJobFixture(data, data.archive.result.calls.length, 0, original ? 'failed' : state.completed ? 'completed' : 'running')
    job.invocation_id = input.invocation_id
    if (original && !state.completed) job.recovery_request = structuredClone(offered)
    if (original && state.completed) job.generation_id = data.job.generation_id
    if (state.corruptOffer && job.recovery_request && 'replies' in job.recovery_request) job.recovery_request.replies.pop()
    await route.fulfill({ json: { id: randomUUID(), tool_id: tool, status: 'completed', input_payload: input, result: { test_design_job: job } } })
  })
  return state
}
