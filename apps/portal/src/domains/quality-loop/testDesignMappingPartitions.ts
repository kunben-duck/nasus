import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { AssertionReview, MappingArchive, MappingPlan } from './types/testDesignMapping'

export const mappingPartSize = 128
export const maxMappingParts = 65536
export type MappingPair = Pick<AssertionReview, 'case_id' | 'row_id' | 'step_index' | 'oracle_digest'>
export function mappingInvariant(value: unknown): asserts value {
  if (!value) throw new Error('Complete partitioned mapping could not be verified')
}
export function compareMappingIds(a: string, b: string) {
  const left = Array.from(a, (c) => c.codePointAt(0)!), right = Array.from(b, (c) => c.codePointAt(0)!)
  for (let i = 0; i < Math.min(left.length, right.length); i++) if (left[i] !== right[i]) return left[i] - right[i]
  return left.length - right.length
}
export async function mappingDigestChain(digests: string[]) {
  const bytes = new Uint8Array(digests.length * 32)
  digests.forEach((digest, index) => {
    mappingInvariant(/^sha256:[0-9a-f]{64}$/.test(digest))
    for (let i = 0; i < 32; i++) bytes[index * 32 + i] = parseInt(digest.slice(7 + i * 2, 9 + i * 2), 16)
  })
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  return 'sha256:' + Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('')
}
export async function mappingGenerationPin(draft: GenerationArchive): Promise<MappingArchive['generation_pin']> {
  return { generation_id: draft.metadata.generation_id, artifact_hash: draft.metadata.artifact_hash,
    context_pin: draft.result.context_pin, scope_pin: draft.result.scope_pin, input_digest: draft.result.request.input_digest,
    proposal_hash: await canonicalDigest(draft.result.proposal) }
}
export async function prepareMappingPlan(draft: GenerationArchive, previous: string | null) {
  const proposal = draft.result.proposal, cases = [...proposal.cases].sort((a, b) => compareMappingIds(a.case_id, b.case_id))
  mappingInvariant(cases.length <= 32768 && new Set(cases.map((c) => c.case_id)).size === cases.length)
  const rows = new Map(proposal.coverage.rows.map((row) => [row.row_id, row]))
  mappingInvariant(rows.size === proposal.coverage.rows.length)
  const partDigests: string[] = []
  let entries: MappingPair[] = [], total = 0
  const flush = async () => {
    partDigests.push(await canonicalDigest({ sequence: partDigests.length, assertions: entries }))
    total += entries.length; entries = []
  }
  for (const item of cases) {
    mappingInvariant(item.assertions.length >= 1 && item.assertions.length <= 256 && item.steps.length <= 64
      && new Set(item.assertions.map((a) => a.row_id)).size === item.assertions.length)
    for (const assertion of [...item.assertions].sort((a, b) => compareMappingIds(a.row_id, b.row_id))) {
      const row = rows.get(assertion.row_id)
      mappingInvariant(row && Number.isInteger(assertion.step_index) && assertion.step_index >= 0 && assertion.step_index < item.steps.length
        && assertion.oracle_digest === row.oracle_digest && assertion.oracle_digest === await canonicalDigest(assertion.oracle))
      entries.push({ case_id: item.case_id, row_id: assertion.row_id, step_index: assertion.step_index, oracle_digest: assertion.oracle_digest })
      if (entries.length === mappingPartSize) await flush()
    }
  }
  if (entries.length) await flush()
  const body: Omit<MappingPlan, 'plan_digest'> = { schema: 'nasus.test-design-mapping-plan.v1',
    policy_revision: 'nasus.test-design-mapping-partition.v1', generation_pin: { project_id: draft.metadata.project_id, ...await mappingGenerationPin(draft) },
    expected_previous_revision_id: previous, case_count: cases.length, assertion_count: total, part_size: 128,
    part_count: partDigests.length, layout_digest: await mappingDigestChain(partDigests), execution_authorized: false }
  return { plan: { ...body, plan_digest: await canonicalDigest(body) }, partDigests }
}
