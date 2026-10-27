import { request } from '../../shared/api/client'
import { isImagePageSizeError } from './imageReadPair'
import type { ReferenceAssertion, ReferencePage } from './referenceReviewApi'

const identifier = (value: unknown): value is string => typeof value === 'string' && value.length > 0
  && value.length <= 128 && value.trim() === value
  && Array.from(value).every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
const digest = (value: unknown) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
const evidence = (value: unknown) => Array.isArray(value) && value.length > 0 && value.length <= 100
  && value.every(identifier) && new Set(value).size === value.length

export interface ReferenceReadPin { imageArtifactHash: string; proposalDigest: string }

function verifyPage(page: ReferencePage, revision: string, proposal: string,
  section: 'assertions' | 'gaps', offset: number, limit: number, pin: ReferenceReadPin) {
  if (page.proposal_id !== proposal || page.image_revision_id !== revision || page.section !== section
    || page.publication !== 'not_in_image_membership' || page.status !== 'proposed'
    || page.method_version !== 'nasus.explicit-requirement-reference.v1'
    || page.digest !== pin.proposalDigest || page.image_artifact_hash !== pin.imageArtifactHash
    || ![page.assertion_count, page.gap_count].every((count) => Number.isSafeInteger(count) && count >= 0)
    || page.assertion_count + page.gap_count > 10000 || !Array.isArray(page.items)) {
    throw new Error('Reference proposal mismatch')
  }
  const total = section === 'assertions' ? page.assertion_count : page.gap_count
  const end = offset + page.items.length
  if (offset > total || page.items.length !== Math.min(limit, total - offset)
    || page.next_offset !== (end < total ? end : null)) throw new Error('Reference pagination mismatch')
  const assertions = new Set<string>()
  for (const item of page.items) {
    if (!identifier(item.subject_object_id) || !identifier(item.reference_id)) throw new Error('Invalid reference endpoint')
    if (section === 'gaps') {
      if (!('reason' in item) || !identifier(item.reason) || 'assertion_id' in item) throw new Error('Invalid reference gap')
    } else {
      const row = item as ReferenceAssertion
      if (![row.assertion_id, row.subject_revision_id, row.object_id, row.object_revision_id].every(identifier)
        || assertions.has(row.assertion_id) || row.predicate !== 'references' || row.status !== 'proposed'
        || row.semantic_kind !== 'observed' || row.applicability !== 'selected_manifest_only_not_business_coverage'
        || !evidence(row.subject_evidence_ids) || !evidence(row.object_evidence_ids)) throw new Error('Invalid reference assertion')
      assertions.add(row.assertion_id)
    }
  }
}

export async function readReferencePage(project: string, revision: string, proposal: string,
  section: 'assertions' | 'gaps', offset: number, signal: AbortSignal, pin: ReferenceReadPin): Promise<ReferencePage> {
  if (![project, revision, proposal].every(identifier) || !['assertions', 'gaps'].includes(section)
    || !Number.isSafeInteger(offset) || offset < 0 || offset > 10000
    || !pin || !digest(pin.imageArtifactHash) || !digest(pin.proposalDigest)) throw new Error('Invalid reference page selection')
  const path = `/v1/projects/${encodeURIComponent(project)}/system-image/reference-proposals/${encodeURIComponent(proposal)}`
  let limit = 20
  for (;;) {
    signal.throwIfAborted()
    try {
      const page = await request<ReferencePage>(`${path}?${new URLSearchParams({ section, offset: String(offset), limit: String(limit) })}`,
        { signal, cache: 'no-store' })
      signal.throwIfAborted()
      verifyPage(page, revision, proposal, section, offset, limit, pin)
      return page
    } catch (error) {
      // Reduce only a failed read window; never retry authorization or mutations.
      if (!isImagePageSizeError(error) || limit === 1) throw error
      limit = Math.max(1, Math.floor(limit / 2))
    }
  }
}
