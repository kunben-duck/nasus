import type { AgentGoal } from '../../../domains/agent/types'
import type { ToolInvocation } from '../../../domains/platform/types'

export function ConfirmationGates({
  pendingGoal,
  pendingBaselineInvocation,
  loading,
  disabled,
  confirmPendingGoal,
  confirmToolInvocation,
}: {
  pendingGoal?: AgentGoal
  pendingBaselineInvocation?: ToolInvocation
  loading: boolean
  disabled: boolean
  confirmPendingGoal: () => void
  confirmToolInvocation: (invocationId: string) => void
}) {
  if (pendingGoal) {
    return (
      <div className="confirmation-gate-card" data-testid="agent-confirmation-gate">
        <div>
          <span className="confirmation-kicker">
            {pendingGoal.pause_reason === 'missing_source_binding' ? 'Source bindings required' : 'Confirmation required'}
          </span>
          <strong>{pendingGoal.title}</strong>
          <p>
            {pendingGoal.pause_reason === 'missing_source_binding'
              ? 'Connect the required code repository and optionally upload historical US documents or test assets to continue the same audited tool chain.'
              : 'The agent paused before a high-risk tool. Confirm in conversation to continue the same audited tool chain.'}
          </p>
        </div>
        {pendingGoal.pause_reason === 'waiting_confirmation' ? (
          <button className="composer-action-button build-submit-button" data-testid="confirm-agent-goal" onClick={confirmPendingGoal} disabled={disabled}>
            {loading ? 'Continuing...' : 'Confirm and continue'}
          </button>
        ) : null}
      </div>
    )
  }

  if (!pendingBaselineInvocation) return null

  return (
    <div className="confirmation-gate-card" data-testid="baseline-confirmation-gate">
      <div>
        <span className="confirmation-kicker">Confirmation required</span>
        <strong>Initialize Official System Image</strong>
        <p>
          Source ingestion and context materialization are complete. Confirm baseline initialization to promote the
          candidate system image into the official project baseline.
        </p>
      </div>
      <button
        className="composer-action-button build-submit-button"
        data-testid="confirm-baseline-invocation"
        onClick={() => confirmToolInvocation(pendingBaselineInvocation.id)}
        disabled={disabled}
      >
        {loading ? 'Confirming...' : 'Confirm baseline'}
      </button>
    </div>
  )
}
