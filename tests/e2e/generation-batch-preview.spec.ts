import { expect, test } from '@playwright/test'
import { verifyBatchGenerationPreview } from '../../apps/portal/src/domains/quality-loop/generationBatchPreviewValidation'
import { verifyGenerationJob, verifyGenerationPreview } from '../../apps/portal/src/domains/quality-loop/testDesignGenerationValidation'
import { batchJobFixture, batchProtocolFixture } from './generation-batch-fixtures'

test('batch preview verifies the Python planning digest and cumulative operator budget, not a single-call consent', async () => {
  const data = batchProtocolFixture(), preview = data.preview, selection = preview.batch_planning!.selection
  expect(await verifyBatchGenerationPreview(preview, selection)).toEqual(preview)
  expect(preview.call_count).toBe(3)
  expect(() => verifyGenerationPreview(preview, selection)).toThrow()
  expect(JSON.stringify(preview)).not.toMatch(/artifact_ref|api_key|Untrusted source observation/)
})

for (const mutation of ['missing', 'duplicate', 'sequence', 'message', 'plan', 'policy', 'binding', 'source', 'budget', 'authority', 'extra-secret', 'estimate']) {
  test(`batch preview rejects ${mutation} without authorizing egress`, async () => {
    const data = batchProtocolFixture(), p = data.preview, plan = p.batch_planning!, selection = structuredClone(plan.selection)
    if (mutation === 'missing') plan.batches.pop()
    if (mutation === 'duplicate') plan.batches[1] = structuredClone(plan.batches[0])
    if (mutation === 'sequence') plan.batches[0].sequence = 1
    if (mutation === 'message') plan.messages_hashes[0] = p.request.input_digest
    if (mutation === 'plan') plan.planning_digest = p.request.input_digest
    if (mutation === 'policy') p.policy.revision = 'changed-without-new-consent'
    if (mutation === 'binding') plan.model_binding.config_digest = p.request.input_digest
    if (mutation === 'source') plan.source_binding_ids = ['foreign-source']
    if (mutation === 'budget') p.reservation.reserved_tokens--
    if (mutation === 'authority') Object.assign(plan, { generation_authorized: true })
    if (mutation === 'extra-secret') Object.assign(plan, { api_key: 'never allowed' })
    if (mutation === 'estimate') plan.batches[0].estimated_input_tokens++
    await expect(verifyBatchGenerationPreview(p, selection)).rejects.toThrow()
  })
}

test('batch progress distinguishes archived partial replies, unknown calls and complete atomic drafts', () => {
  const v = batchProtocolFixture()
  for (const job of [batchJobFixture(v), batchJobFixture(v, 1), batchJobFixture(v, 1, 1, 'failed'),
    batchJobFixture(v, 1, 0, 'cancelled'), batchJobFixture(v, 3, 0, 'completed')]) {
    expect(verifyGenerationJob(job, v.scope, job.invocation_id)).toEqual(job)
  }
  const partial = batchJobFixture(v, 1)
  expect(partial.reply_archived).toBe(false); expect(partial.provider_outcome_unknown).toBe(false)
  expect(partial.batch_progress!.unstarted_calls).toBe(2)
})

for (const mutation of ['partial-complete', 'unknown', 'unstarted', 'release', 'invoice', 'cost', 'output', 'extra-field', 'recovery']) {
  test(`batch progress rejects ${mutation} rather than showing an unsafe task state`, () => {
    const v = batchProtocolFixture(), job = batchJobFixture(v, 1), b = job.batch_progress!
    if (mutation === 'partial-complete') { job.status = 'completed'; job.generation_id = v.job.generation_id }
    if (mutation === 'unknown') job.provider_outcome_unknown = true
    if (mutation === 'unstarted') b.unstarted_calls--
    if (mutation === 'release') Object.assign(b, { reservation_released: true })
    if (mutation === 'invoice') Object.assign(b, { invoice_verified: true })
    if (mutation === 'cost') b.known_cost_nanos_at_policy_rates = b.reservation.reserved_cost_nanos + 1
    if (mutation === 'output') b.known_output_tokens = b.reservation.max_output_tokens_per_call + 1
    if (mutation === 'extra-field') Object.assign(b.reservation, { api_key: 'not metadata' })
    if (mutation === 'recovery') job.recovery_request = { project_id: job.project_id, invocation_id: job.invocation_id,
      request_hash: b.plan_digest, reply_artifact_hash: b.plan_digest, response_hash: b.plan_digest }
    expect(() => verifyGenerationJob(job, v.scope, job.invocation_id)).toThrow()
  })
}
