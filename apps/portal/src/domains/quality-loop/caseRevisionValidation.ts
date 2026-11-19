import { generationEqual } from './testDesignGenerationValidation'
import type { GenerationArchive, PlannedCase } from './types/testDesignGeneration'

export function caseRevisionRequest(draft: GenerationArchive, cases: PlannedCase[], reason: string) {
  cases = cases.map((item) => ({ ...item, title: item.title.trim(),
    preconditions: item.preconditions.map((text) => text.trim()), inputs: item.inputs.map((text) => text.trim()),
    steps: item.steps.map((text) => text.trim()) }))
  const originals = new Map(draft.result.proposal.cases.map((item) => [item.case_id, item]))
  const oracles = (item: PlannedCase) => item.assertions.map(({ row_id, oracle_digest, oracle }) => ({ row_id, oracle_digest, oracle }))
    .sort((a, b) => a.row_id < b.row_id ? -1 : a.row_id > b.row_id ? 1 : 0)
  if (!draft.current_use.scope_current || !reason.trim() || reason.trim().length > 2000 || !cases.length
    || cases.length > 512 || new Set(cases.map((item) => item.case_id)).size !== cases.length
    || !cases.some((item) => !generationEqual(item, originals.get(item.case_id)))) throw new Error('Select a current case and explicit changes')
  for (const item of cases) {
    const before = originals.get(item.case_id)
    if (!before || !item.title.trim() || item.title.length > 2000
      || ![item.preconditions, item.inputs, item.steps].every((lines) => lines.length > 0 && lines.length <= 64
        && lines.every((line) => !!line.trim() && line.length <= 2000))
      || !['global_constraint_ids', 'supporting_fact_ids', 'reused_case_ids'].every((key) =>
        generationEqual(item[key as keyof PlannedCase], before[key as keyof PlannedCase]))
      || !generationEqual(oracles(item), oracles(before))
      || item.assertions.some((a) => !Number.isSafeInteger(a.step_index) || a.step_index < 0 || a.step_index >= item.steps.length)) {
      throw new Error('Case edits must retain approved business expectations and source obligations')
    }
  }
  return { project_id: draft.metadata.project_id, generation_id: draft.metadata.generation_id,
    generation_artifact_hash: draft.metadata.artifact_hash, cases, reason: reason.trim() }
}

export function verifySavedCaseRevision(value: GenerationArchive, draft: GenerationArchive,
  request: ReturnType<typeof caseRevisionRequest>, actorId: string, invocationId: string) {
  const r = value.result, m = value.metadata, prior = draft.result
  const expected = new Map(request.cases.map((item) => [item.case_id, item]))
  if (r.schema !== 'nasus.test-design-case-revision.v1' || m.project_id !== request.project_id
    || m.invocation_id !== invocationId || r.actor_id !== actorId || m.generation_id === draft.metadata.generation_id
    || !generationEqual(r.edit_request, request) || r.parent?.generation_id !== request.generation_id
    || r.parent.artifact_hash !== request.generation_artifact_hash
    || r.original_generation_id !== (prior.original_generation_id ?? draft.metadata.generation_id)
    || r.edit_sequence !== (prior.edit_sequence ?? 0) + 1
    || !generationEqual(r.context_pin, prior.context_pin) || !generationEqual(r.scope_pin, prior.scope_pin)
    || !generationEqual(r.proposal.cases, prior.proposal.cases.map((item) => expected.get(item.case_id) ?? item))) {
    throw new Error('Case revision does not match the original confirmed edit')
  }
  return value
}
