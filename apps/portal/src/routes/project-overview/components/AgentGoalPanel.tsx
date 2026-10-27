import type { AgentGoal, AgentGoalExplanation } from '../../../domains/agent/types'
import { activeGoalSteps } from '../../../domains/agent/activePlanPhase'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function AgentGoalPanel({ goal, explanation }: { goal?: AgentGoal; explanation?: AgentGoalExplanation }) {
  const { t, tx } = useI18n()
  if (!goal) return null

  const visibleSteps = goal.steps
    .filter((step) => step.phase || step.selected_tool_id || step.status !== 'pending')
    .slice(-9)
  const totalSteps = goal.steps.length || goal.max_steps || 1
  const completedSteps = goal.steps.filter((step) => step.status === 'completed').length
  let currentStep: AgentGoal['steps'][number] | undefined
  let currentPhaseUnverified = false
  if (!['completed', 'cancelled'].includes(goal.status)) {
    try {
      const activeSteps = activeGoalSteps(goal)
      currentStep = [...activeSteps].reverse().find((step) => step.status === 'running' || step.status === 'blocked')
        ?? activeSteps.find((step) => step.status === 'pending') ?? activeSteps.at(-1)
    } catch {
      currentPhaseUnverified = true
    }
  }
  const detailSteps = visibleSteps.slice(-5)

  return (
    <div className="agent-goal-panel" data-testid="agent-goal-panel">
      <div className="agent-goal-summary">
        <span className={`agent-goal-status ${goal.status}`}>{tx(goal.status)}</span>
        <div>
          <strong>{tx(goal.title)}</strong>
          <p>{tx(goal.summary)}</p>
        </div>
        <span className="agent-goal-progress">{completedSteps}/{totalSteps}</span>
      </div>
      <div className="agent-goal-planning-facts" data-testid="agent-goal-planning-facts">
        <span>{goal.planner_kind ?? 'planner'}</span>
        {goal.goal_template ? <span>{goal.goal_template}</span> : null}
        {goal.target_refs?.length ? <span>{t('{count} targets', { count: goal.target_refs.length })}</span> : null}
        {goal.query_keys?.length ? <span>{t('{count} refresh keys', { count: goal.query_keys.length })}</span> : null}
        <span>{t('{used}/{max} model calls', { used: goal.model_calls_used, max: goal.max_model_calls })}</span>
        <span>{t('{used}/{max} tokens', { used: formatTokens(goal.thinking_tokens_used), max: formatTokens(goal.max_thinking_tokens) })}</span>
        <span>{t('{used}/{max} no progress', { used: goal.no_progress_observations, max: goal.max_no_progress_observations })}</span>
      </div>
      {goal.budget_exhausted_reason ? (
        <div className="agent-explanation-reason" data-testid="agent-budget-exhausted">
          {t('Runtime paused by {reason}.', { reason: tx(goal.budget_exhausted_reason.replaceAll('_', ' ')) })}
        </div>
      ) : null}
      {currentStep ? (
        <div className="agent-current-step" data-testid="agent-current-step" data-step-id={currentStep.id}>
          <div>
            <span className="eyebrow">{t('Current agent step')}</span>
            <strong>{tx(currentStep.title)}</strong>
            <p>{agentStepNarrative(currentStep, t, tx)}</p>
          </div>
          <span className={`agent-phase-pill ${currentStep.phase ?? currentStep.status}`}>
            {tx(currentStep.phase ?? currentStep.status)}
          </span>
        </div>
      ) : null}
      {currentPhaseUnverified ? (
        <div className="agent-explanation-reason" role="alert" data-testid="agent-current-step-unverified">
          {t('The active phase checkpoint could not be verified. Historical steps remain visible; refresh before continuing.')}
        </div>
      ) : null}
      {explanation ? (
        <div className="agent-explanation-card" data-testid="agent-goal-explanation">
          <div className="agent-explanation-main">
            <span className="eyebrow">{t('Agent explanation')}</span>
            <strong>{tx(explanationLabel(explanation.waiting_on))}</strong>
            <p>{tx(explanation.next_action)}</p>
          </div>
          <div className="agent-explanation-facts">
            {explanation.planner_kind ? <span>{explanation.planner_kind}</span> : null}
            {explanation.goal_template ? <span>{explanation.goal_template}</span> : null}
            <span>{t('phase {phase}', { phase: tx(explanation.phase) })}</span>
            <span>{t('{count} tools', { count: explanation.tool_invocation_refs.length })}</span>
            <span>{t('{count} memories', { count: explanation.memory_refs.length })}</span>
            <span>{t('{count} audits', { count: explanation.audit_event_refs.length })}</span>
          </div>
          {explanation.planning_summary ? (
            <div className="agent-explanation-reason">{tx(explanation.planning_summary)}</div>
          ) : null}
          <div className="agent-explanation-reason">
            {tx(explanation.reasoning_summary)}
          </div>
          {explanation.memory_context?.summary ? (
            <div className="agent-explanation-memory">
              <span>{t('memory')}</span>
              <p>{tx(explanation.memory_context.summary)}</p>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="agent-step-rail">
        {visibleSteps.map((step) => (
          <div className={`agent-step-pill ${step.status}`} key={step.id}>
            <span className="agent-step-dot" />
            <span className="agent-step-label">{step.selected_tool_id ?? tx(step.phase ?? step.title)}</span>
            <span className="agent-step-status">{tx(step.status)}</span>
          </div>
        ))}
      </div>
      {detailSteps.length ? (
        <div className="agent-loop-trace" data-testid="agent-loop-trace">
          <div className="agent-loop-trace-header">
            <span className="eyebrow">{t('Agent loop trace')}</span>
            <strong>{t('Think · Act · Observe · Decide')}</strong>
          </div>
          <div className="agent-loop-card-grid">
            {detailSteps.map((step) => (
              <div className={`agent-loop-card ${step.status}`} key={`${step.id}-detail`}>
                <div className="agent-loop-card-head">
                  <span>{tx(step.phase ?? 'step')}</span>
                  <strong>{step.selected_tool_id ?? tx(step.title)}</strong>
                </div>
                <p>{agentStepNarrative(step, t, tx)}</p>
                <div className="agent-loop-card-meta">
                  {step.tool_invocation_id ? <span>{t('tool {id}', { id: step.tool_invocation_id })}</span> : null}
                  {step.memory_retrieval_run_refs?.length ? <span>{t('{count} retrieval runs', { count: step.memory_retrieval_run_refs.length })}</span> : null}
                  {step.memory_recent_turn_count ? <span>{t('{count} turns', { count: step.memory_recent_turn_count })}</span> : null}
                  {step.decision ? <span>{t('decision {decision}', { decision: tx(step.decision) })}</span> : null}
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
  if (waitingOn === 'source_capture') return 'Waiting for captured code'
  if (waitingOn === 'candidate_review') return 'Review the structural candidate'
  if (waitingOn === 'plan_phase_review') return 'Review the new build phase'
  if (waitingOn === 'completion_review') return 'Review findings before publication'
  if (waitingOn === 'human_review') return 'Review the failed goal'
  if (waitingOn === 'user_decision') return 'Waiting for a budget decision'
  if (waitingOn === 'user_resume') return 'Waiting to continue the goal'
  if (waitingOn === 'user_confirmation') return 'Waiting for confirmation'
  if (waitingOn === 'approval') return 'Waiting for approval'
  if (waitingOn === 'agent_runtime') return 'Agent is running'
  if (waitingOn === 'none') return 'No blocker'
  return waitingOn.replaceAll('_', ' ')
}

function agentStepNarrative(step: AgentGoal['steps'][number], t: ReturnType<typeof useI18n>['t'], tx: ReturnType<typeof useI18n>['tx']) {
  if (step.reasoning) return tx(step.reasoning)
  if (step.observation_summary) return tx(step.observation_summary)
  if (step.decision_rationale) return tx(step.decision_rationale)
  if (step.selected_tool_id) return t('Executing {tool} through the canonical tool runtime.', { tool: step.selected_tool_id })
  if (step.next_plan_hint) return t('Next recommended tool: {tool}.', { tool: step.next_plan_hint })
  return step.status === 'running' ? t('Agent is processing this step.') : t('Step is recorded in the agent loop trace.')
}

function formatTokens(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`
  if (value >= 1_000) return `${Math.round(value / 1_000)}k`
  return String(value)
}
