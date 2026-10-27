import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import { requireScript, scriptId, scriptNumber } from './automationScriptValidation'
import type { ScriptArchive, ScriptActionDecision, ScriptOracleDecision, ScriptReviewArchive, ScriptReviewAssessment, ScriptReviewView } from './types/automationScripts'

export async function newScriptDecisions(draft: ScriptArchive) {
  const actions: ScriptActionDecision[] = [], assertions: ScriptOracleDecision[] = []
  for (const script of draft.result.proposal.scripts) {
    for (const [index, action] of script.actions.entries()) actions.push({ case_id: script.case_id, action_index: index,
      action_digest: await canonicalDigest(action), decision: 'defer', reason: '' })
    for (const oracle of script.assertions) assertions.push({ case_id: script.case_id, row_id: oracle.row_id,
      action_index: oracle.action_index, source_step_index: oracle.source_step_index,
      oracle_digest: oracle.oracle_digest, decision: 'defer', reason: '' })
  }
  return { actions, assertions }
}
export const scriptReason = (value: unknown): value is string => typeof value === 'string' && !!value.trim() && [...value].length <= 2000
export function scriptDecisionsValid(actions: ScriptActionDecision[], assertions: ScriptOracleDecision[]) {
  return [...actions, ...assertions].every((item) => ['accept', 'reject', 'defer'].includes(item.decision) && scriptReason(item.reason))
}
export async function scriptPin(draft: ScriptArchive) {
  const r = draft.result, p = r.prepared
  return { script_revision_id: r.script_revision_id, artifact_hash: draft.metadata.artifact_hash,
    input_digest: r.request.input_digest, proposal_hash: await canonicalDigest(r.proposal),
    context_pin: p.context_pin, scope_pin: p.scope_pin, generation_pin: p.generation_pin, mapping_pin: p.mapping_pin }
}
async function assessment(draft: ScriptArchive, actions: ScriptActionDecision[], assertions: ScriptOracleDecision[]): Promise<ScriptReviewAssessment> {
  const expected = await newScriptDecisions(draft)
  requireScript(Array.isArray(actions) && Array.isArray(assertions) && actions.length === expected.actions.length
    && assertions.length === expected.assertions.length && scriptDecisionsValid(actions, assertions))
  for (const [actual, original, keys] of [[actions, expected.actions, ['case_id', 'action_index', 'action_digest']],
    [assertions, expected.assertions, ['case_id', 'row_id', 'action_index', 'source_step_index', 'oracle_digest']]] as const) {
    const seen = new Set<string>()
    for (const item of actual) {
      const originalItem = original.find((e) => keys.every((key) => generationEqual(e[key as keyof typeof e], item[key as keyof typeof item])))
      const identity = JSON.stringify(keys.map((key) => item[key as keyof typeof item]))
      requireScript(originalItem && !seen.has(identity)); seen.add(identity)
    }
  }
  const values = [...actions, ...assertions], count = (decision: string) => values.filter((item) => item.decision === decision).length
  return { review_complete: !!draft.result.proposal.scripts.length && !draft.result.proposal.gaps.length && !count('reject') && !count('defer'),
    reviewed_action_count: actions.length, reviewed_oracle_count: assertions.length, accepted_count: count('accept'),
    rejected_count: count('reject'), deferred_count: count('defer'), gap_count: draft.result.proposal.gap_count,
    automated_count: 0, executed_on_target_count: 0, passed_count: 0, execution_authorized: false,
    remaining_gates: ['target_build_environment_binding', 'api_or_dom_locator_evidence', 'fixture_setup_cleanup', 'immutable_run_plan'] }
}
export async function verifyScriptReviewArchive(value: unknown, draft: ScriptArchive): Promise<ScriptReviewArchive> {
  const v = value as ScriptReviewArchive, r = v?.request, m = v?.revision
  requireScript(r && m && r.project_id === draft.metadata.project_id && r.script_revision_id === draft.metadata.script_revision_id
    && r.script_artifact_hash === draft.metadata.artifact_hash && r.policy_revision === 'nasus.automation-script-review.v1'
    && scriptReason(r.reason) && ['review', 'withdraw'].includes(r.decision)
    && m.project_id === r.project_id && m.script_revision_id === r.script_revision_id && m.script_artifact_hash === r.script_artifact_hash
    && scriptId(m.revision_id) && scriptNumber(m.sequence, 1000) && m.sequence > 0
    && m.previous_revision_id === r.expected_previous_revision_id && (m.sequence === 1 ? m.previous_revision_id === null : scriptId(m.previous_revision_id))
    && scriptId(m.authority_actor) && scriptId(m.invocation_id) && typeof m.recorded_at === 'string' && Number.isFinite(Date.parse(m.recorded_at))
    && m.status === (r.decision === 'review' ? 'reviewed' : 'withdrawn') && generationDigest(m.artifact_hash)
    && await canonicalDigest(r) === m.request_hash && generationEqual(v.script_pin, await scriptPin(draft)))
  const expected = r.decision === 'review' ? await assessment(draft, r.actions!, r.assertions!) : null
  requireScript(generationEqual(v.assessment, expected) && (r.decision === 'review' || r.actions === null && r.assertions === null))
  requireScript(await canonicalDigest({ schema: 'nasus.automation-script-review.v1', project_id: r.project_id, request: r,
    script_pin: v.script_pin, assessment: v.assessment, authority_actor: m.authority_actor,
    invocation_id: m.invocation_id, recorded_at: m.recorded_at }) === m.artifact_hash)
  return v
}
export async function verifyScriptReviewView(value: unknown, draft: ScriptArchive): Promise<ScriptReviewView> {
  const v = value as ScriptReviewView
  requireScript(v && v.project_id === draft.metadata.project_id && v.script_revision_id === draft.metadata.script_revision_id
    && v.script_artifact_hash === draft.metadata.artifact_hash && generationEqual(v.script_pin, await scriptPin(draft))
    && typeof v.can_review === 'boolean' && typeof v.input_current === 'boolean' && v.execution_authorized === false
    && (!v.input_current || draft.current_use.input_current)
    && Array.isArray(v.history) && v.history.length <= 1000 && new Set(v.history.map((r) => r.revision_id)).size === v.history.length)
  for (const [i, m] of v.history.entries()) requireScript(scriptId(m.revision_id) && m.project_id === v.project_id && m.script_revision_id === v.script_revision_id
    && m.script_artifact_hash === v.script_artifact_hash && m.sequence === i + 1 && m.previous_revision_id === (i ? v.history[i - 1].revision_id : null)
    && ['reviewed', 'withdrawn'].includes(m.status) && (m.status !== 'withdrawn' || i > 0 && v.history[i - 1].status === 'reviewed')
    && [m.artifact_hash, m.request_hash].every(generationDigest) && scriptId(m.authority_actor) && scriptId(m.invocation_id))
  if (v.head) {
    await verifyScriptReviewArchive(v.head, draft)
    requireScript(generationEqual(v.head.revision, v.history.at(-1)))
  } else requireScript(v.head === null && !v.history.length)
  return v
}
