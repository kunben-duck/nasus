import { request } from '../../shared/api/client'
import type { AgentGoal, ConversationSession } from '../agent/types'
import type { ToolInvocation } from '../platform/types'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { buildPlanApi, verifyBuildTarget } from './buildPlanApi'
import type { BuildPlan } from './types/buildPlan'

const id = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value)
const refs = (plan: BuildPlan) => [`project:${plan.project_id}`, `build_plan:${plan.plan_id}`, `build_plan_digest:${plan.plan_digest}`]
const waitRef = 'build_source_wait_digest:'

async function requireOriginalWait(plan: BuildPlan, goal: AgentGoal, signal?: AbortSignal) {
  const intent = plan.proposal.intent
  const body = { project_id: plan.project_id, objective: intent.objective, mode: intent.mode, target: intent.target }
  const digest = await canonicalDigest(body)
  const waiting = goal.steps.filter((step) => step.phase === 'acting')[0]
  if (goal.target_refs?.filter((ref) => ref.startsWith(waitRef)).length !== 1
    || !goal.target_refs.includes(waitRef + digest)
    || waiting?.selected_tool_id !== 'query.system_image.status' || waiting.status !== 'completed'
    || waiting.tool_input_payload?.project_id !== plan.project_id || !id(waiting.tool_invocation_id)
    || await canonicalDigest(waiting.tool_input_payload?.build_input_request) !== digest
    || goal.steps.filter((step) => step.phase === 'acting' && 'build_input_request' in (step.tool_input_payload ?? {})).length !== 1) {
    throw new Error('Original waiting build intent changed')
  }
  const command = await request<ToolInvocation>(`/v1/tool-invocations/${encodeURIComponent(waiting.tool_invocation_id)}`,
    { signal, cache: 'no-store' })
  if (command.id !== waiting.tool_invocation_id || command.conversation_id !== goal.conversation_id
    || command.tool_id !== 'query.system_image.status' || command.status !== 'completed'
    || command.input_payload?.agent_goal_id !== goal.id || command.input_payload?.project_id !== plan.project_id
    || await canonicalDigest(command.input_payload?.build_input_request) !== digest
    || command.result?.invocation_id !== command.id || command.result.status !== 'completed'
    || command.result.object_refs.length !== 1 || command.result.object_refs[0] !== `project:${plan.project_id}`) {
    throw new Error('Original waiting status command could not be verified')
  }
  return waitRef + digest
}

function requirePlan(plan: BuildPlan) {
  const intent = plan?.proposal?.intent
  if (!intent || plan.proposal.policy_version !== 'nasus.image-investigation-plan.v3'
    || !id(plan.project_id) || !id(plan.plan_id) || !/^sha256:[a-f0-9]{64}$/.test(plan.plan_digest)
    || intent.project_id !== plan.project_id || plan.proposal.state !== 'draft'
    || plan.proposal.execution_ready !== false || plan.proposal.authorization_state !== 'not_granted') {
    throw new Error('Saved build entry requires a fixed v3 plan')
  }
  verifyBuildTarget(intent.target!, plan.project_id, intent.target?.target_baseline_id ?? '')
  const bindings = intent.sources.map((source) => source.binding_id)
  const code = intent.sources.filter((source) => source.source_type === 'code')
  if (intent.expected_head_status !== 'resolved' || intent.expected_head !== intent.target!.expected_head_id
    || JSON.stringify(bindings) !== JSON.stringify(intent.scope_binding_ids)
    || bindings.length !== new Set(bindings).size || !bindings.length
    || !code.length || code.some((source) => source.status !== 'captured')
    || intent.sources.some((source) => !id(source.binding_id) || !['code', 'us_doc', 'test_asset'].includes(source.source_type)
      || !['captured', 'failed', 'pending', 'legacy_unverified'].includes(source.status)
      || (source.status === 'captured' ? !id(source.source_revision_id) : source.source_revision_id !== null))) {
    throw new Error('Saved build entry source scope mismatch')
  }
}

async function requirePreparedGoal(plan: BuildPlan, goal: AgentGoal, signal?: AbortSignal) {
  const intent = plan.proposal.intent
  const body = { project_id: plan.project_id, source_manifest_id: intent.source_manifest_id,
    objective: intent.objective, mode: intent.mode, purpose: intent.purpose, budget: intent.budget, target: intent.target }
  const digest = await canonicalDigest(body)
  const waited = goal.target_refs?.some((ref) => ref.startsWith(waitRef))
  const originalWait = waited ? await requireOriginalWait(plan, goal, signal) : undefined
  const expected = [`project:${plan.project_id}`, `source_manifest:${intent.source_manifest_id}`,
    `build_target:${intent.target!.target_baseline_id}`, `build_request_digest:${digest}`,
    ...(originalWait ? [originalWait] : []), ...refs(plan).slice(1)]
  const acting = goal.steps.filter((step) => step.phase === 'acting')
  const offset = waited ? 1 : 0
  const preparation = acting[offset]
  if (goal.target_refs?.length !== expected.length || !expected.every((ref, index) => goal.target_refs?.[index] === ref)
    || acting.filter((step) => step.selected_tool_id === 'system_image.build.plan').length !== 1
    || preparation?.selected_tool_id !== 'system_image.build.plan' || preparation.status !== 'completed'
    || !id(preparation.tool_invocation_id)) throw new Error('Prepared build goal scope mismatch')
  const original = Object.fromEntries(Object.keys(body).map((key) => [key, preparation.tool_input_payload?.[key]]))
  if (await canonicalDigest(original) !== digest) throw new Error('Prepared build request changed')
  const command = await request<ToolInvocation>(`/v1/tool-invocations/${encodeURIComponent(preparation.tool_invocation_id)}`,
    { signal, cache: 'no-store' })
  const commandBody = Object.fromEntries(Object.keys(body).map((key) => [key, command.input_payload?.[key]]))
  if (command.id !== preparation.tool_invocation_id || command.conversation_id !== goal.conversation_id
    || command.tool_id !== 'system_image.build.plan' || command.status !== 'completed'
    || command.input_payload?.agent_goal_id !== goal.id || await canonicalDigest(commandBody) !== digest
    || command.result?.invocation_id !== command.id || command.result.status !== 'completed'
    || command.result.followup_reason !== 'build_plan_review' || command.result.requires_followup !== true
    || command.result.object_refs.length !== 1 || command.result.object_refs[0] !== `build_plan:${plan.plan_id}`) {
    throw new Error('Prepared build command could not be verified')
  }
  return acting.slice(offset + 1, offset + 4)
}

export async function verifySavedBuildGoal(plan: BuildPlan, conversationId: string, goal: AgentGoal, signal?: AbortSignal) {
  requirePlan(plan)
  if (!id(conversationId) || !goal || !id(goal.id) || goal.conversation_id !== conversationId
    || goal.project_id !== plan.project_id || goal.goal_template !== 'system_image_build'
    || !Array.isArray(goal.target_refs)
    || !refs(plan).every((ref) => goal.target_refs?.includes(ref))) throw new Error('Saved build goal scope mismatch')
  const prepared = goal.target_refs.some((ref) => ref.startsWith('build_request_digest:'))
  if (!prepared && goal.target_refs.length !== 3) throw new Error('Saved build goal scope mismatch')
  const prefix = prepared ? await requirePreparedGoal(plan, goal, signal)
    : goal.steps.filter((step) => step.phase === 'acting').slice(0, 3)
  const tools = ['query.system_image.build_plans.read', 'system_image.build.authorize', 'system_image.build.structure']
  if (prefix.length !== 3 || prefix.some((step, index) => step.selected_tool_id !== tools[index]
    || step.tool_input_payload?.project_id !== plan.project_id || step.tool_input_payload?.plan_id !== plan.plan_id)) {
    throw new Error('Saved build goal compiler mismatch')
  }
  if (prefix.slice(1).some((step) => step.tool_input_payload?.plan_digest !== plan.plan_digest
    || step.tool_input_payload?.target_baseline_id !== plan.proposal.intent.target!.target_baseline_id)) {
    throw new Error('Saved build goal target changed')
  }
  const budget = prefix[1].tool_input_payload?.budget as Record<string, unknown> | undefined
  if (!budget || budget.max_tool_calls !== 1 || budget.max_model_calls !== 0 || budget.max_cost_microusd !== 0
    || !Number.isInteger(budget.max_active_seconds) || Number(budget.max_active_seconds) < 1
    || Number(budget.max_active_seconds) > Math.min(plan.proposal.intent.budget.max_active_seconds, 1800)) {
    throw new Error('Saved build goal consent scope changed')
  }
  return goal
}

function requireConversation(plan: BuildPlan, conversation: ConversationSession, conversationId?: string) {
  requirePlan(plan)
  if (!conversation || !id(conversation.id) || (conversationId && conversation.id !== conversationId)
    || conversation.space_type !== 'project' || conversation.space_id !== plan.project_id
    || conversation.project_id !== plan.project_id || !Array.isArray(conversation.agent_goals)) {
    throw new Error('Saved build conversation scope mismatch')
  }
  return conversation
}

export const savedBuildAgentApi = {
  async conversation(plan: BuildPlan) {
    requirePlan(plan)
    return requireConversation(plan, await request<ConversationSession>('/v1/conversations', { method: 'POST',
      body: JSON.stringify({ space_type: 'project', space_id: plan.project_id, title: 'System image build' }) }))
  },
  async start(plan: BuildPlan, conversationId: string) {
    requirePlan(plan)
    if (!id(conversationId)) throw new Error('Saved build conversation identity is invalid')
    const goal = await request<AgentGoal>('/v1/agent-goals', { method: 'POST', body: JSON.stringify({
      conversation_id: conversationId, project_id: plan.project_id, goal_template: 'system_image_build',
      title: 'Build from saved system image intent', summary: 'Build the fixed candidate and review its remaining gaps.',
      goal_description: 'Use the original inputs and target. Execution and publication require separate gates.',
      target_refs: refs(plan), max_runtime_seconds: Math.min(plan.proposal.intent.budget.max_active_seconds, 1800),
    }) })
    return verifySavedBuildGoal(plan, conversationId, goal)
  },
  async recover(plan: BuildPlan, conversationId: string, signal: AbortSignal) {
    requirePlan(plan)
    if (!id(conversationId)) throw new Error('Saved build conversation identity is invalid')
    const current = await buildPlanApi.read(plan.project_id, plan.plan_id, signal)
    if (current.plan_digest !== plan.plan_digest) throw new Error('Saved build plan digest changed')
    const conversation = requireConversation(plan, await request<ConversationSession>(`/v1/conversations/${encodeURIComponent(conversationId)}`,
      { signal, cache: 'no-store' }), conversationId)
    const matching = conversation.agent_goals.filter((goal) => refs(plan).every((ref) => goal.target_refs?.includes(ref)))
    if (matching.length !== 1) throw new Error('Saved build outcome is still unknown; do not resubmit')
    return verifySavedBuildGoal(plan, conversationId, matching[0], signal)
  },
}
