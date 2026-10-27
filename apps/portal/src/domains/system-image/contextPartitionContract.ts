import type { TestDesignContext } from './types/contextPack'

// Supplement the server's immutable replay: missing rules or duplicate ACs must
// never appear to be a complete bundle in the UI.
export function verifyPartitions(bundle: TestDesignContext, verifyPart: (part: TestDesignContext) => void) {
  const parts = bundle.parts
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
  const globals = bundle.required_constraints.filter((item) => item.kind === 'business_rule').map((item) => item.object_id)
  const targets = bundle.required_constraints.filter((item) => item.kind === 'acceptance_criterion').map((item) => item.object_id)
  if (!parts?.length || parts.length > 256 || bundle.budget.scope !== 'per_part' || bundle.budget.part_count !== parts.length
      || new Set(parts.map((p) => p.part_id)).size !== parts.length) throw new Error('Context partition count mismatch')
  const seen: string[] = [], facts = new Map<string, TestDesignContext['facts'][number]>()
  for (const { part_id: id, context } of parts) {
    verifyPart(context)
    const partition = context.partition
    if (!/^sha256:[0-9a-f]{64}$/.test(id) || !partition || partition.rule_inheritance !== 'all_source_business_rules'
        || !same(partition.global_constraint_ids, globals) || !same(context.retrieval, bundle.retrieval)
        || !same(context.publication_pin, bundle.publication_pin)
        || context.source_manifest_id !== bundle.source_manifest_id || context.source_manifest_hash !== bundle.source_manifest_hash
        || new Set(partition.target_object_ids).size !== partition.target_object_ids.length
        || partition.target_object_ids.some((target) => !targets.includes(target))
        || targets.length > 0 && !partition.target_object_ids.length) throw new Error('Context partition scope mismatch')
    const expected = bundle.required_constraints.filter((item) => globals.includes(item.object_id) || partition.target_object_ids.includes(item.object_id))
    if (!same(context.required_constraints, expected)) throw new Error('Context partition lost or changed mandatory constraints')
    seen.push(...partition.target_object_ids)
    context.facts.forEach((fact) => facts.set(JSON.stringify(fact), fact))
  }
  if (!same(seen, targets) || !same([...facts.values()], bundle.facts)
      || bundle.budget.used_upper_bound !== Math.max(...parts.map((p) => p.context.budget.used_upper_bound))
      || bundle.budget.total_upper_bound !== parts.reduce((sum, p) => sum + p.context.budget.used_upper_bound, 0)) throw new Error('Context partition union mismatch')
}
