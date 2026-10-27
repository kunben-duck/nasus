import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { readReferencePage, type ReferenceReadPin } from './referencePageRead'

export interface ReferenceAssertion {
  assertion_id: string
  subject_object_id: string
  subject_revision_id: string
  object_id: string
  object_revision_id: string
  subject_evidence_ids: string[]
  object_evidence_ids: string[]
  reference_id: string
  predicate: 'references'
  semantic_kind: 'observed'
  status: 'proposed'
  applicability: 'selected_manifest_only_not_business_coverage'
}
export interface ReferenceGap { subject_object_id: string; reference_id: string; reason: string }
export interface ReferencePage {
  proposal_id: string; digest: string; image_revision_id: string; section: 'assertions' | 'gaps'
  image_artifact_hash: string
  status: 'proposed'; method_version: 'nasus.explicit-requirement-reference.v1'
  assertion_count: number; gap_count: number; items: (ReferenceAssertion | ReferenceGap)[]; next_offset: number | null
  publication: 'not_in_image_membership'
}
export type ReviewChoice = 'accept' | 'reject' | 'defer'
export interface LinkDecision {
  decision_id: string; decision: ReviewChoice; reviewer_actor: string; reason: string; recorded_at: string; sequence: number
}
export interface ReviewPage {
  project_id: string; proposal_id: string; assertion_id: string; image_revision_id: string
  proposal_digest: string; evidence_digest: string; policy_revision: string
  head_decision_id: string | null; total: number; items: LinkDecision[]; next_offset: number | null
  publication: 'not_in_image_membership'
}
const root = (project: string) => `/v1/projects/${encodeURIComponent(project)}/system-image`
const proposalRoot = (project: string, proposal: string) => `${root(project)}/reference-proposals/${encodeURIComponent(proposal)}`
export const referenceReviewApi = {
  async freeze(page: ReviewPage, parentArtifactHash: string) {
    if (!page.head_decision_id) throw new Error('An explicit decision is required')
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.revisions.freeze_links', idempotency_key: crypto.randomUUID(), input: {
      project_id: page.project_id, parent_revision_id: page.image_revision_id, parent_artifact_hash: parentArtifactHash,
      proposal_id: page.proposal_id, proposal_digest: page.proposal_digest, decision_ids: [page.head_decision_id],
    } })
    if (pending.status !== 'waiting_confirmation') throw new Error('Freeze requires explicit confirmation')
    const result = await platformApi.confirmToolInvocation(pending.id)
    if (result.status !== 'completed') throw new Error('Freeze failed; reload the latest review before retrying')
    const revision = result.result?.object_refs?.find((ref) => ref.startsWith('image_revision:'))?.slice('image_revision:'.length)
    if (!revision) throw new Error('Missing frozen revision receipt')
    return revision
  },
  async list(project: string, revision: string, cursor: string, signal: AbortSignal) {
    const page = await request<{ image_revision_id: string; items: { proposal_id: string; digest: string }[]; next_after_id: string | null }>(
      `${root(project)}/revisions/${encodeURIComponent(revision)}/reference-proposals?${new URLSearchParams({ after_id: cursor })}`,
      { signal, cache: 'no-store' })
    if (page.image_revision_id !== revision) throw new Error('Reference image mismatch')
    return page
  },
  async page(project: string, revision: string, proposal: string, section: 'assertions' | 'gaps', offset: number, signal: AbortSignal, pin: ReferenceReadPin) {
    return readReferencePage(project, revision, proposal, section, offset, signal, pin)
  },
  async history(project: string, revision: string, proposal: string, assertion: string, offset: number, signal: AbortSignal, proposalDigest: string) {
    if (!/^sha256:[0-9a-f]{64}$/.test(proposalDigest)) throw new Error('Invalid reference history selection')
    const page = await request<ReviewPage>(`${proposalRoot(project, proposal)}/assertions/${encodeURIComponent(assertion)}/decisions?offset=${offset}`, { signal, cache: 'no-store' })
    if (page.project_id !== project || page.proposal_id !== proposal || page.assertion_id !== assertion || page.image_revision_id !== revision
        || page.proposal_digest !== proposalDigest || page.publication !== 'not_in_image_membership') throw new Error('Review scope mismatch')
    return page
  },
  async propose(project: string, revision: string) {
    const result = await platformApi.invokeTool({ tool_id: 'system_image.links.propose_references', idempotency_key: crypto.randomUUID(), input: {
      project_id: project, image_revision_id: revision,
    } })
    if (result.status !== 'completed') throw new Error('Reference derivation failed')
  },
  async review(page: ReviewPage, decision: ReviewChoice, reason: string) {
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.links.review', idempotency_key: crypto.randomUUID(), input: {
      project_id: page.project_id, proposal_id: page.proposal_id, assertion_id: page.assertion_id,
      proposal_digest: page.proposal_digest, evidence_digest: page.evidence_digest, policy_revision: page.policy_revision,
      expected_previous_decision_id: page.head_decision_id, decision, reason,
    } })
    if (pending.status !== 'waiting_confirmation') throw new Error('Review requires explicit confirmation')
    const result = await platformApi.confirmToolInvocation(pending.id)
    if (result.status !== 'completed') throw new Error('Review did not complete; reload before resubmitting')
  },
}
