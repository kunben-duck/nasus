import { oracleKeys, type ObservableOracle } from './types/observableOracle'
import type { TestDesignContext } from '../system-image/types/contextPack'
import type { ScopeDimension, ScopeObligation, TestDesignContract } from './types/testDesignScope'

export const scopeDimensions: ScopeDimension[] = ['risks', 'permissions', 'transitions', 'invariants']
export const dimensionFields = {
  risks: ['boundary'], permissions: ['actor', 'operation', 'resource', 'expected'],
  transitions: ['from_state', 'event', 'to_state'], invariants: ['invariant'],
} as const
export const blankOracle = (): ObservableOracle => ({ preconditions: '', action: '', observation: '', expected_result: '' })
export const newScopeObligation = (dimension: ScopeDimension): ScopeObligation => ({
  obligation_id: crypto.randomUUID(), constraint_ids: [], evidence_ids: [], oracle: blankOracle(),
  ...Object.fromEntries(dimensionFields[dimension].map((field) => [field, ''])),
})
export function newScopeContract(context: TestDesignContext): TestDesignContract {
  const empty = () => ({ applicability: '' as const, rationale: '', items: [] })
  return { authority_basis: 'user_confirmed_test_design_scope', risks: empty(), permissions: empty(), transitions: empty(), invariants: empty(),
    examples: context.required_constraints.map((item) => ({ constraint_id: item.object_id,
      positive: item.oracle ? { ...item.oracle } : blankOracle(), negative: null, negative_not_applicable_reason: null, negative_gap_id: null })),
    reused_case_ids: [], reuse_assessment: '', conflicts: [], conflict_assessment: '', gaps: [] }
}
export const scopeTextValid = (value: unknown): value is string => typeof value === 'string' && !!value.trim() && value.length <= 2000
const oracleValid = (value: ObservableOracle | null) => !!value && oracleKeys.every((key) => scopeTextValid(value[key]))
const sameSet = (a: string[], b: string[]) => a.length === b.length && new Set(a).size === a.length && a.every((id) => b.includes(id))
export function scopeContractValid(contract: TestDesignContract, context: TestDesignContext): boolean {
  const ids = context.required_constraints.map((item) => item.object_id)
  const evidence = [...context.required_constraints.flatMap((item) => item.evidence_ids), ...context.facts.flatMap((item) => item.endpoint.evidence_ids)]
  const cases = context.facts.filter((item) => item.relation === 'asserts').map((item) => item.endpoint.object_id)
  const refs = (values: string[], available: string[], required = false) => values.length <= 256 && (!required || values.length > 0)
    && new Set(values).size === values.length && values.every((id) => available.includes(id))
  const uniqueIds = (values: string[]) => new Set(values).size === values.length && values.every((id) => !!id.trim() && id.length <= 128)
  if (!context.publication_pin || !ids.length || ids.length > 256 || context.required_constraints.some((item) => !item.oracle || item.authority.status !== 'approved')
    || contract.authority_basis !== 'user_confirmed_test_design_scope'
    || !sameSet(contract.examples.map((item) => item.constraint_id), ids)) return false
  for (const dimension of scopeDimensions) {
    const group = contract[dimension]
    if (!scopeTextValid(group.rationale) || !['applicable', 'not_applicable'].includes(group.applicability)
      || (group.applicability === 'applicable') !== !!group.items.length || group.items.length > 256) return false
    for (const item of group.items) {
      if (!refs(item.constraint_ids, ids, true) || !refs(item.evidence_ids, evidence) || !oracleValid(item.oracle)
        || dimensionFields[dimension].some((key) => !scopeTextValid(item[key]))
        || (dimension === 'permissions' && !['allowed', 'denied'].includes(item.expected ?? ''))) return false
    }
  }
  if (!uniqueIds(scopeDimensions.flatMap((key) => contract[key].items.map((item) => item.obligation_id)))
    || !refs(contract.reused_case_ids, cases) || !scopeTextValid(contract.reuse_assessment) || !scopeTextValid(contract.conflict_assessment)) return false
  for (const items of [contract.gaps, contract.conflicts]) {
    if (items.length > 256 || !uniqueIds(items.map((item) => item.id))
      || items.some((item) => !refs(item.constraint_ids, ids, true) || !scopeTextValid(item.description))) return false
  }
  if (contract.conflicts.some((item) => item.resolution !== null && !scopeTextValid(item.resolution))) return false
  return contract.examples.every((item) => oracleValid(item.positive)
    && [item.negative, item.negative_not_applicable_reason, item.negative_gap_id].filter((value) => value !== null).length === 1
    && (item.negative ? oracleValid(item.negative) : item.negative_not_applicable_reason !== null ? scopeTextValid(item.negative_not_applicable_reason)
      : contract.gaps.some((gap) => gap.id === item.negative_gap_id && gap.constraint_ids.includes(item.constraint_id))))
}
