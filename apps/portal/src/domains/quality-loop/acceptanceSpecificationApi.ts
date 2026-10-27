import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { oracleKeys, type ObservableOracle } from './types/observableOracle'
export { oracleKeys, type ObservableOracle } from './types/observableOracle'

export interface AcceptanceSelection {
  project_id: string; image_revision_id: string; image_artifact_hash: string; object_id: string
  binding_id: string; source_revision_id: string; document_revision_id: string
}
export type AuthorityKind = 'acceptance_criterion' | 'business_rule'
export interface AcceptanceRevision extends AcceptanceSelection {
  revision_id: string; ac_id?: string; rule_id?: string; basis_digest: string; status: 'approved' | 'withdrawn'
  previous_revision_id: string | null; sequence: number; authority_actor: string; invocation_id: string
  recorded_at: string; artifact_hash: string; policy_revision: string
}
export interface AcceptanceView {
  ac_id?: string; rule_id?: string; policy_revision: string; basis_digest: string; revision_count: number; can_review: boolean
  applicability: 'exact_image_only'; image_publication: 'unchanged'
  basis: AcceptanceSelection & { parent_document_revision_id: string; entity_id: string; payload_hash: string; evidence_ids: string[]
    source_authority: 'unapproved_source_projection'; fields: { name: string; value: string; start_line: number; end_line: number; snippet_hash: string }[] }
  head: AcceptanceRevision | null
  current: { revision: AcceptanceRevision; oracle: ObservableOracle | null; authority_basis: 'user_confirmed_requirement' | 'user_confirmed_business_rule' | null
    reason: string; historical_not_live: true } | null
}

const authorityContract = (kind: AuthorityKind) => kind === 'business_rule' ? {
  policy: 'nasus.business-rule-authority.v1', id: 'rule_id' as const, otherId: 'ac_id' as const, prefix: 'rule_',
  basis: 'user_confirmed_business_rule', path: 'business-rules', tool: 'quality.business_rule.review',
  object: 'business_rule:', stale: 'stale_business_rule_authority',
} : {
  policy: 'nasus.acceptance-authority.v1', id: 'ac_id' as const, otherId: 'rule_id' as const, prefix: 'ac_',
  basis: 'user_confirmed_requirement', path: 'acceptance-specifications', tool: 'quality.acceptance_specification.review',
  object: 'acceptance_specification:', stale: 'stale_acceptance_authority',
}
const digest = (value: string) => /^sha256:[0-9a-f]{64}$/.test(value)
export class StaleAcceptanceAuthority extends Error {}

export function verifyAcceptance(view: AcceptanceView, selection: AcceptanceSelection, evidenceIds: string[], kind: AuthorityKind = 'acceptance_criterion') {
  const contract = authorityContract(kind)
  const b = view.basis
  if (Object.entries(selection).some(([key, value]) => b[key as keyof AcceptanceSelection] !== value)
      || view.policy_revision !== contract.policy || view.applicability !== 'exact_image_only' || view.image_publication !== 'unchanged'
      || !new RegExp(`^${contract.prefix}[0-9a-f]{64}$`).test(view[contract.id] ?? '') || view[contract.otherId] !== undefined
      || !digest(view.basis_digest) || !digest(b.payload_hash)
      || b.source_authority !== 'unapproved_source_projection' || !b.parent_document_revision_id || !b.entity_id
      || !b.evidence_ids.length || new Set(b.evidence_ids).size !== b.evidence_ids.length || b.evidence_ids.some((id) => !evidenceIds.includes(id))
      || !b.fields.length || b.fields.some((field) => field.name !== kind || !field.value.trim()
        || !digest(field.snippet_hash) || !Number.isInteger(field.start_line) || field.start_line < 1 || field.end_line < field.start_line)
      || !Number.isInteger(view.revision_count) || view.revision_count < 0 || view.revision_count > 1000
      || typeof view.can_review !== 'boolean') throw new Error('Acceptance source scope mismatch')
  if (!view.head) {
    if (view.current !== null || view.revision_count !== 0) throw new Error('Unexpected acceptance authority')
    return view
  }
  const h = view.head, c = view.current
  if (!c || Object.entries(selection).some(([key, value]) => h[key as keyof AcceptanceSelection] !== value)
      || h[contract.id] !== view[contract.id] || h[contract.otherId] !== undefined || h.basis_digest !== view.basis_digest || h.policy_revision !== contract.policy
      || h.sequence !== view.revision_count || (h.sequence === 1) !== (h.previous_revision_id === null)
      || !h.revision_id || !h.invocation_id || !h.authority_actor || !digest(h.artifact_hash)
      || !['approved', 'withdrawn'].includes(h.status) || !c.reason.trim() || c.historical_not_live !== true
      || Object.entries(h).some(([key, value]) => c.revision[key as keyof AcceptanceRevision] !== value)) throw new Error('Acceptance authority scope mismatch')
  if (h.status === 'approved') {
    if (c.authority_basis !== contract.basis || !c.oracle
        || oracleKeys.some((key) => !c.oracle![key]?.trim() || c.oracle![key].length > 2000)) throw new Error('Acceptance oracle incomplete')
  } else if (c.oracle !== null || c.authority_basis !== null) throw new Error('Withdrawn authority cannot expose a current oracle')
  return view
}

export const acceptanceSpecificationApi = {
  async inspect(selection: AcceptanceSelection, evidenceIds: string[], signal: AbortSignal, kind: AuthorityKind = 'acceptance_criterion') {
    const params = new URLSearchParams({ image_revision_id: selection.image_revision_id, image_artifact_hash: selection.image_artifact_hash,
      object_id: selection.object_id })
    const view = await request<AcceptanceView>(`/v1/projects/${encodeURIComponent(selection.project_id)}/quality/${authorityContract(kind).path}?${params}`,
      { signal, cache: 'no-store' })
    return verifyAcceptance(view, selection, evidenceIds, kind)
  },
  async record(view: AcceptanceView, decision: 'approve' | 'withdraw', oracle: ObservableOracle, reason: string, attempt: string, kind: AuthorityKind = 'acceptance_criterion') {
    const contract = authorityContract(kind)
    if (!view.can_review || !reason.trim() || reason.length > 2000 || (decision === 'withdraw' && view.head?.status !== 'approved')) {
      throw new Error('Invalid acceptance review')
    }
    const b = view.basis
    if (view.policy_revision !== contract.policy) throw new Error('Authority kind changed')
    const pending = await platformApi.invokeTool({ tool_id: contract.tool, idempotency_key: attempt,
      input: { project_id: b.project_id, image_revision_id: b.image_revision_id, image_artifact_hash: b.image_artifact_hash, object_id: b.object_id,
        basis_digest: view.basis_digest, expected_previous_revision_id: view.head?.revision_id ?? null, policy_revision: view.policy_revision,
        decision, oracle: decision === 'approve' ? oracle : null, authority_basis: decision === 'approve' ? contract.basis : null, reason } })
    if (pending.status !== 'waiting_confirmation') throw new Error('Explicit authority confirmation required')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.result?.followup_reason === contract.stale) throw new StaleAcceptanceAuthority('Authority changed')
    if (done.status !== 'completed' || !done.result?.object_refs.some((ref) => ref.startsWith(contract.object))) {
      throw new Error('Acceptance authority was not acknowledged')
    }
    return done.id
  },
}
