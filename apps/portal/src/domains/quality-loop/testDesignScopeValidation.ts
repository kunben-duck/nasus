import type { ContextArchive } from '../system-image/types/contextPack'
import { scopeContractValid, scopeDimensions, scopeTextValid } from './testDesignScopeDraft'
import type { ScopeArchive, ScopeRevision, ScopeView } from './types/testDesignScope'

const digest = (value: string) => /^sha256:[0-9a-f]{64}$/.test(value)
const equal = (a: unknown, b: unknown): boolean => {
  if (a === b) return true
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false
  return Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([key, value]) => equal(value, (b as Record<string, unknown>)[key]))
}
function verifyRevision(revision: ScopeRevision, context: ContextArchive) {
  const m = context.metadata
  if (revision.project_id !== m.project_id || revision.context_id !== m.context_id || revision.context_artifact_hash !== m.artifact_hash
    || !/^scope_[0-9a-f]{64}$/.test(revision.scope_id) || !revision.revision_id || !revision.invocation_id || !revision.authority_actor
    || !digest(revision.artifact_hash) || !digest(revision.request_hash) || !Number.isInteger(revision.sequence) || revision.sequence < 1
    || !['approved', 'withdrawn'].includes(revision.status)) throw new Error('Scope revision mismatch')
}
export function verifyScopeArchive(value: ScopeArchive, context: ContextArchive, expected: ScopeRevision | string) {
  const r = value.revision, q = value.request, c = value.current_use, m = context.metadata
  verifyRevision(r, context)
  if ((typeof expected === 'string' ? r.revision_id !== expected : !equal(r, expected))
    || value.historical_not_live !== true || c.generation_authorized !== false
    || typeof c.scope_current !== 'boolean' || typeof c.scope_complete !== 'boolean'
    || q.project_id !== r.project_id || q.context_id !== r.context_id || q.context_artifact_hash !== r.context_artifact_hash
    || q.expected_previous_revision_id !== r.previous_revision_id || q.policy_revision !== 'nasus.test-design-scope.v1'
    || q.decision !== (r.status === 'approved' ? 'approve' : 'withdraw') || !scopeTextValid(q.reason)
    || !equal(value.context_pin, { context_id: m.context_id, artifact_hash: m.artifact_hash, input_digest: m.input_digest,
      image_revision_id: m.image_revision_id, image_artifact_hash: m.image_artifact_hash })) throw new Error('Scope archive pin mismatch')
  if (!q.contract) {
    if (r.status !== 'withdrawn' || value.assessment !== null || c.scope_current || c.scope_complete) throw new Error('Withdrawn scope mismatch')
  } else {
    if (r.status !== 'approved' || !scopeContractValid(q.contract, context.context)) throw new Error('Scope contract mismatch')
    const blockers = [...q.contract.conflicts.filter((item) => item.resolution === null).map((item) => `unresolved_conflict:${item.id}`),
      ...q.contract.gaps.map((item) => `explicit_gap:${item.id}`)]
    const assessment = { constraint_ids: context.context.required_constraints.map((item) => item.object_id).sort(),
      obligation_ids: scopeDimensions.flatMap((key) => q.contract![key].items.map((item) => item.obligation_id)).sort(), blockers,
      scope_complete: !blockers.length, generation_authorized: false, use_policy: 'reviewed_scope_only_requires_separate_generation_preflight' }
    if (!equal(value.assessment, assessment) || c.scope_complete !== (c.scope_current && !blockers.length)) throw new Error('Scope assessment mismatch')
  }
  return value
}
export function verifyScopeView(view: ScopeView, context: ContextArchive) {
  const m = context.metadata
  if (!/^scope_[0-9a-f]{64}$/.test(view.scope_id) || view.context_id !== m.context_id || view.context_artifact_hash !== m.artifact_hash
    || typeof view.can_review !== 'boolean' || typeof view.context_current_use.stale !== 'boolean' || view.context_current_use.generation_authorized !== false
    || view.history.length > 1000 || Boolean(view.head) !== Boolean(view.history.length)) throw new Error('Scope inspection mismatch')
  view.history.forEach((revision, i) => {
    verifyRevision(revision, context)
    if (revision.scope_id !== view.scope_id || revision.sequence !== i + 1 || revision.previous_revision_id !== (view.history[i - 1]?.revision_id ?? null)) throw new Error('Scope history mismatch')
  })
  if (view.head) {
    verifyScopeArchive(view.head, context, view.history.at(-1)!)
    if (view.head.current_use.scope_current !== (view.head.revision.status === 'approved' && !view.context_current_use.stale)) throw new Error('Scope head mismatch')
  }
  return view
}
