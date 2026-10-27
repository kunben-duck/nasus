import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import type { GenerationBatchArchive } from '../../apps/portal/src/domains/quality-loop/types/generationBatchResult'
import type { ScopeArchive } from '../../apps/portal/src/domains/quality-loop/types/testDesignScope'
import type { GenerationJob, GenerationPreview } from '../../apps/portal/src/domains/quality-loop/types/testDesignGeneration'

export interface BatchProtocolFixture {
  archive: GenerationBatchArchive
  scope: ScopeArchive
  job: Pick<GenerationJob, 'project_id' | 'generation_id' | 'source_invocation_id' | 'invocation_id'>
  preview: GenerationPreview
}

// The Python fixture uses production serializers, not a second hand-built
// protocol. It never persists a result or calls an external model.
export function batchProtocolFixture(context?: unknown, scope?: ScopeArchive, recoveryId?: string): BatchProtocolFixture {
  const script = `import json,sys
from apps.api.tests.test_generation_batch_results import public_result_fixture
data=json.load(sys.stdin)
print(json.dumps(public_result_fixture(data.get('context'), data.get('scope'), recovery_invocation_id=data.get('recoveryId')),ensure_ascii=False))`
  return JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c', script], {
    input: JSON.stringify({ context, scope, recoveryId }), encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
  }))
}

export function batchJobFixture(data: BatchProtocolFixture, archived = 0, unknown = 0, status: GenerationJob['status'] = 'running'): GenerationJob {
  const r = data.archive.result, claimed = archived + unknown, count = r.calls.length
  const replies = r.calls.slice(0, archived).map((call) => call.reply.usage)
  return { ...data.job, scope_revision_id: r.request.scope_revision_id, status,
    generation_id: status === 'completed' ? data.job.generation_id : null,
    call_reserved: claimed > 0, reply_archived: archived === count, provider_outcome_unknown: unknown > 0,
    recovery_request: null, execution_authorized: false,
    batch_progress: { schema: 'nasus.test-design-batch-progress.v1', plan_digest: r.reservation.plan_digest,
      call_count: count, claimed_calls: claimed, archived_calls: archived, unknown_calls: unknown, unstarted_calls: count - claimed,
      known_input_tokens: replies.reduce((n, usage) => n + usage.input_tokens, 0),
      known_output_tokens: replies.reduce((n, usage) => n + usage.output_tokens, 0),
      known_cost_nanos_at_policy_rates: replies.reduce((n, usage) => n + usage.cost_nanos_at_policy_rates, 0),
      reservation: structuredClone(r.reservation.reservation), reservation_released: false, invoice_verified: false, execution_authorized: false } }
}
