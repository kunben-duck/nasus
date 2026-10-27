import { expect, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { batchJobFixture, type BatchProtocolFixture } from './generation-batch-fixtures'
import type { GenerationJob } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'

// Only generation transport is simulated. The browser uses real isolated PG
// identities, sources, publication, approved fixture constraints and scope.
export async function installBatchProtocol(page: Page, data: BatchProtocolFixture) {
  type Command = { id: string; tool_id: string; status: string; input_payload: Record<string, unknown> }
  const writes: Command[] = [], pending = new Map<string, Command>()
  const state = { writes, previews: 0, jobs: 0, archived: 1, unknown: 0, status: 'running' as GenerationJob['status'],
    submitted: false, corruptPreview: false, corruptProgress: false, denied: false }
  const job = () => {
    const value = batchJobFixture(data, state.archived, state.unknown, state.status)
    if (state.corruptProgress) Object.assign(value.batch_progress!, { invoice_verified: true })
    return value
  }
  await page.route('**/v1/settings/model-configs?route=chat', (route) => route.fulfill({ json: {
    route: 'chat', configurations: [{ config_id: data.preview.request.model_config_id, display_name: 'Explicit native batch protocol model',
      route: 'chat', legacy_imported: false, last_test_result: { ok: true }, last_test_signature: 'explicit-batch-fixture' }] } }))
  await page.route('**/quality/test-design-jobs?*', async (route) => {
    const params = new URL(route.request().url()).searchParams
    if (state.denied) return route.fulfill({ status: 403, json: { detail: 'Explicit access revocation fixture' } })
    expect(params.get('scope_revision_id')).toBe(data.preview.request.scope_revision_id)
    expect(params.get('scope_artifact_hash')).toBe(data.preview.request.scope_artifact_hash)
    const request = { project_id: data.job.project_id, scope_revision_id: params.get('scope_revision_id'),
      scope_artifact_hash: params.get('scope_artifact_hash'), after_id: params.get('after_id'), limit: Number(params.get('limit')) }
    await route.fulfill({ json: { request, items: state.submitted ? [{ invocation_id: data.job.invocation_id,
      source_invocation_id: data.job.source_invocation_id, tool_id: 'quality.test_design.generate', status: state.status }] : [],
      next_after_id: null, has_running: state.submitted && state.status === 'running', generation_authorized: false, execution_authorized: false } })
  })
  await page.route('**/quality/test-design-results/*', (route) => state.denied
    ? route.fulfill({ status: 403, json: { detail: 'Explicit result revocation fixture' } })
    : route.fulfill({ json: data.archive }))
  await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!, row = pending.get(id)
    if (!row) return route.continue()
    row.input_payload.confirmed_by_user = true
    if (row.tool_id === 'quality.test_design.cancel') { state.status = 'cancelled'; row.status = 'completed' }
    else { state.submitted = true; row.status = 'running' }
    pending.delete(id)
    await route.fulfill({ json: row })
  })
  await page.route('**/v1/tool-invocations', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const { tool_id: tool, input, idempotency_key: key } = route.request().postDataJSON()
    if (!['query.quality.test_design_batches', 'query.quality.test_design_job', 'quality.test_design.generate',
      'quality.test_design.cancel', 'quality.test_design.recover', 'query.quality.test_design_execution'].includes(tool)) return route.continue()
    expect(key).toBeTruthy()
    expect(tool).not.toBe('query.quality.test_design_execution')
    expect(tool).not.toBe('quality.test_design.recover')
    const row: Command & { result?: unknown } = { id: randomUUID(), tool_id: tool, status: 'completed', input_payload: { ...input } }
    if (tool === 'query.quality.test_design_batches') {
      state.previews++
      expect(input).toEqual(data.preview.batch_planning!.selection)
      const preview = structuredClone(data.preview)
      if (state.corruptPreview) preview.batch_planning!.messages_hashes[0] = preview.request.input_digest
      row.result = { test_design_execution_preview: preview }
    } else if (tool === 'query.quality.test_design_job') {
      state.jobs++
      expect(input).toEqual({ project_id: data.job.project_id, invocation_id: data.job.invocation_id })
      if (state.denied) return route.fulfill({ status: 403, json: { detail: 'Explicit job access revocation fixture' } })
      row.result = { test_design_job: job() }
    } else {
      if (tool === 'quality.test_design.generate') {
        expect(state.submitted).toBe(false)
        expect(input).toEqual(data.preview.request)
        row.id = data.job.invocation_id
      } else expect(input).toEqual({ project_id: data.job.project_id, invocation_id: data.job.invocation_id })
      row.status = 'waiting_confirmation'; pending.set(row.id, row); writes.push(row)
    }
    await route.fulfill({ json: row })
  })
  return state
}
