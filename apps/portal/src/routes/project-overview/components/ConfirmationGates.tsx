import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { AgentGoal } from '../../../domains/agent/types'
import { activeGoalSteps } from '../../../domains/agent/activePlanPhase'
import type { ToolInvocation } from '../../../domains/platform/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { buildReviewHref } from '../../../domains/system-image/buildReviewHandoff'

export function ConfirmationGates({
  pendingGoal,
  pendingBaselineInvocation,
  loading,
  disabled,
  confirmPendingGoal,
  continueStructuralInvestigation,
  confirmToolInvocation,
}: {
  pendingGoal?: AgentGoal
  pendingBaselineInvocation?: ToolInvocation
  loading: boolean
  disabled: boolean
  confirmPendingGoal: () => Promise<void>
  continueStructuralInvestigation: () => Promise<void>
  confirmToolInvocation: (invocationId: string) => void
}) {
  const { t, tx } = useI18n()
  const actionLock = useRef(false)
  const [failedGate, setFailedGate] = useState<string | null>(null)
  const blocked = pendingGoal && activeGoalSteps(pendingGoal).find((step) => step.phase === 'acting' && step.status === 'blocked')
  const authorizing = blocked?.selected_tool_id === 'system_image.build.authorize'
  const rawBudget = authorizing ? blocked.tool_input_payload?.budget : undefined
  const budget = rawBudget && typeof rawBudget === 'object' && !Array.isArray(rawBudget) ? rawBudget as Record<string, unknown> : undefined
  const budgetValid = budget && ['max_tool_calls', 'max_model_calls', 'max_active_seconds', 'max_cost_microusd']
    .every((key) => typeof budget[key] === 'number' && Number.isSafeInteger(budget[key]) && Number(budget[key]) >= 0)
  const gateKey = `${pendingGoal?.id}:${pendingGoal?.pause_reason}:${blocked?.tool_invocation_id}`
  async function runGate(operation: () => Promise<void>) {
    if (actionLock.current || disabled || failedGate === gateKey) return
    actionLock.current = true
    try {
      await operation()
    } catch {
      setFailedGate(gateKey)
    } finally {
      actionLock.current = false
    }
  }
  if (pendingGoal) {
    const structural = pendingGoal.pause_reason === 'structural_candidate_review'
    const investigation = pendingGoal.pause_reason === 'waiting_confirmation' && blocked?.selected_tool_id === 'system_image.build.investigate'
    const references = pendingGoal.pause_reason === 'reference_candidate_review' && blocked?.selected_tool_id === 'system_image.links.propose_references'
    const reviewing = pendingGoal.pause_reason === 'build_completion_review'
    const reviewHref = reviewing ? buildReviewHref(pendingGoal) : undefined
    const prepared = pendingGoal.pause_reason === 'build_plan_phase_prepared'
    const missingSources = ['missing_source_binding', 'missing_captured_code'].includes(pendingGoal.pause_reason ?? '')
    return (
      <div className="confirmation-gate-card" data-testid="agent-confirmation-gate">
        <div>
          <span className="confirmation-kicker">
            {structural ? t('Structural candidate saved') : references ? t('Reference candidates saved') : prepared ? t('Revised phase prepared. The goal is still paused.') : reviewing ? t('Build review required')
              : missingSources ? t('Source bindings required') : t('Confirmation required')}
          </span>
          <strong>{tx(pendingGoal.title)}</strong>
          <p>
            {prepared ? t('Continue the revised phase to review its independent execution budget. This action does not confirm that budget.')
              : structural ? t('Continue this goal to prepare an evidence investigation of the saved candidate. A separate confirmation follows; no model calls or publication are authorized.')
              : investigation ? t('Confirm reading archived evidence and saving a gap-driven investigation revision for this goal. This does not run repository code, call models or publish the image.')
              : references ? t('Continue this goal to inspect every reference candidate and gap. This does not accept relationships, approve requirements or prove test coverage.')
              : reviewing ? t('Investigation results and unresolved gaps are saved. This is not a completed or published system image.')
              : missingSources
              ? t('Connect the required code repository and optionally upload historical US documents or test assets to continue the same audited tool chain.')
              : t('The agent paused before a high-risk tool. Confirm in conversation to continue the same audited tool chain.')}
          </p>
          {authorizing && budgetValid && budget ? <p data-testid="image-build-execution-budget">
            {t('Structural builds')}: {Number(budget.max_tool_calls)} · {t('Model calls')}: {Number(budget.max_model_calls)} ·{' '}
            {t('Active time limit (seconds)')}: {Number(budget.max_active_seconds)} ·{' '}
            {t('Model cost limit (micro-USD)')}: {Number(budget.max_cost_microusd)}
          </p> : null}
          {failedGate === gateKey ? <p role="alert">{t('The action could not be acknowledged. Reload the project to verify its current step before another action; no automatic retry was sent.')}</p> : null}
        </div>
        {reviewHref ? <Link className="composer-action-button build-submit-button" data-testid="review-saved-build-findings"
          to={reviewHref}>{t('Review saved findings')}</Link> : structural ? (
          <button className="composer-action-button build-submit-button" data-testid="continue-structural-investigation"
            onClick={() => { void runGate(continueStructuralInvestigation) }} disabled={disabled || failedGate === gateKey}>
            {loading ? t('Continuing...') : t('Continue evidence investigation')}
          </button>
        ) : pendingGoal.pause_reason === 'waiting_confirmation' || prepared || references ? (
          <button className="composer-action-button build-submit-button" data-testid={references ? 'inspect-agent-reference-candidates' : 'confirm-agent-goal'}
            onClick={() => { void runGate(confirmPendingGoal) }} disabled={disabled || failedGate === gateKey || (authorizing && !budgetValid)}>
            {loading ? t('Continuing...') : references ? t('Inspect reference candidates') : prepared ? t('Continue revised phase') : investigation ? t('Confirm evidence investigation') : t('Confirm and continue')}
          </button>
        ) : null}
      </div>
    )
  }

  if (!pendingBaselineInvocation) return null

  return (
    <div className="confirmation-gate-card" data-testid="baseline-confirmation-gate">
      <div>
        <span className="confirmation-kicker">{t('Confirmation required')}</span>
        <strong>{t('Initialize Official System Image')}</strong>
        <p>{t('Source ingestion and context materialization are complete. Confirm baseline initialization to promote the candidate system image into the official project baseline.')}</p>
      </div>
      <button
        className="composer-action-button build-submit-button"
        data-testid="confirm-baseline-invocation"
        onClick={() => confirmToolInvocation(pendingBaselineInvocation.id)}
        disabled={disabled}
      >
        {loading ? t('Confirming...') : t('Confirm baseline')}
      </button>
    </div>
  )
}
