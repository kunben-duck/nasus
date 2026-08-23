import type { AgentGoal, AgentGoalExplanation } from '../../../domains/agent/types'

export function AgentGoalPanel({ goal, explanation }: { goal?: AgentGoal; explanation?: AgentGoalExplanation }) {
  if (!goal) return null

  const visibleSteps = goal.steps
    .filter((step) => step.phase || step.selected_tool_id || step.status !== 'pending')
    .slice(-9)
  const totalSteps = goal.steps.length || goal.max_steps || 1
  const completedSteps = goal.steps.filter((step) => step.status === 'completed').length
  const currentStep = [...visibleSteps].reverse().find((step) => step.status === 'running' || step.status === 'blocked') ?? visibleSteps.at(-1)
  const detailSteps = visibleSteps.slice(-5)

  return (
    <div className="agent-goal-panel" data-testid="agent-goal-panel">
      <div className="agent-goal-summary">
        <span className={`agent-goal-status ${goal.status}`}>{goal.status}</span>
        <div>
          <strong>{goal.title}</strong>
          <p>{goal.summary}</p>
        </div>
        <span className="agent-goal-progress">{completedSteps}/{totalSteps}</span>
      </div>
      <div className="agent-goal-planning-facts" data-testid="agent-goal-planning-facts">
        <span>{goal.planner_kind ?? 'planner'}</span>
        {goal.goal_template ? <span>{goal.goal_template}</span> : null}
        {goal.target_refs?.length ? <span>{goal.target_refs.length} targets</span> : null}
        {goal.query_keys?.length ? <span>{goal.query_keys.length} refresh keys</span> : null}
        <span>{goal.model_calls_used}/{goal.max_model_calls} model calls</span>
        <span>{formatTokens(goal.thinking_tokens_used)}/{formatTokens(goal.max_thinking_tokens)} tokens</span>
        <span>{goal.no_progress_observations}/{goal.max_no_progress_observations} no progress</span>
      </div>
      {goal.budget_exhausted_reason ? (
        <div className="agent-explanation-reason" data-testid="agent-budget-exhausted">
          Runtime paused by {goal.budget_exhausted_reason.replaceAll('_', ' ')}.
        </div>
      ) : null}
      {currentStep ? (
        <div className="agent-current-step" data-testid="agent-current-step">
          <div>
            <span className="eyebrow">Current agent step</span>
            <strong>{currentStep.title}</strong>
            <p>{agentStepNarrative(currentStep)}</p>
          </div>
          <span className={`agent-phase-pill ${currentStep.phase ?? currentStep.status}`}>
            {currentStep.phase ?? currentStep.status}
          </span>
        </div>
      ) : null}
      {explanation ? (
        <div className="agent-explanation-card" data-testid="agent-goal-explanation">
          <div className="agent-explanation-main">
            <span className="eyebrow">Agent explanation</span>
            <strong>{explanationLabel(explanation.waiting_on)}</strong>
            <p>{explanation.next_action}</p>
          </div>
          <div className="agent-explanation-facts">
            {explanation.planner_kind ? <span>{explanation.planner_kind}</span> : null}
            {explanation.goal_template ? <span>{explanation.goal_template}</span> : null}
            <span>phase {explanation.phase}</span>
            <span>{explanation.tool_invocation_refs.length} tools</span>
            <span>{explanation.memory_refs.length} memories</span>
            <span>{explanation.audit_event_refs.length} audits</span>
          </div>
          {explanation.planning_summary ? (
            <div className="agent-explanation-reason">{explanation.planning_summary}</div>
          ) : null}
          <div className="agent-explanation-reason">
            {explanation.reasoning_summary}
          </div>
          {explanation.memory_context?.summary ? (
            <div className="agent-explanation-memory">
              <span>memory</span>
              <p>{explanation.memory_context.summary}</p>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="agent-step-rail">
        {visibleSteps.map((step) => (
          <div className={`agent-step-pill ${step.status}`} key={step.id}>
            <span className="agent-step-dot" />
            <span className="agent-step-label">{step.selected_tool_id ?? step.phase ?? step.title}</span>
            <span className="agent-step-status">{step.status}</span>
          </div>
        ))}
      </div>
      {detailSteps.length ? (
        <div className="agent-loop-trace" data-testid="agent-loop-trace">
          <div className="agent-loop-trace-header">
            <span className="eyebrow">Agent loop trace</span>
            <strong>Think · Act · Observe · Decide</strong>
          </div>
          <div className="agent-loop-card-grid">
            {detailSteps.map((step) => (
              <div className={`agent-loop-card ${step.status}`} key={`${step.id}-detail`}>
                <div className="agent-loop-card-head">
                  <span>{step.phase ?? 'step'}</span>
                  <strong>{step.selected_tool_id ?? step.title}</strong>
                </div>
                <p>{agentStepNarrative(step)}</p>
                <div className="agent-loop-card-meta">
                  {step.tool_invocation_id ? <span>tool {step.tool_invocation_id}</span> : null}
                  {step.memory_retrieval_run_refs?.length ? <span>{step.memory_retrieval_run_refs.length} retrieval run</span> : null}
                  {step.memory_recent_turn_count ? <span>{step.memory_recent_turn_count} turns</span> : null}
                  {step.decision ? <span>decision {step.decision}</span> : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function explanationLabel(waitingOn: string) {
  if (waitingOn === 'source_binding') return 'Waiting for source bindings'
  if (waitingOn === 'user_confirmation') return 'Waiting for confirmation'
  if (waitingOn === 'approval') return 'Waiting for approval'
  if (waitingOn === 'agent_runtime') return 'Agent is running'
  if (waitingOn === 'none') return 'No blocker'
  return waitingOn.replaceAll('_', ' ')
}

function agentStepNarrative(step: AgentGoal['steps'][number]) {
  if (step.reasoning) return step.reasoning
  if (step.observation_summary) return step.observation_summary
  if (step.decision_rationale) return step.decision_rationale
  if (step.selected_tool_id) return `Executing ${step.selected_tool_id} through the canonical tool runtime.`
  if (step.next_plan_hint) return `Next recommended tool: ${step.next_plan_hint}.`
  return step.status === 'running' ? 'Agent is processing this step.' : 'Step is recorded in the agent loop trace.'
}

function formatTokens(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`
  if (value >= 1_000) return `${Math.round(value / 1_000)}k`
  return String(value)
}
