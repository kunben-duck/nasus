import type { AgentGoal } from '../../../domains/agent/types'

export function ThinkingCard({ goal }: { goal?: AgentGoal }) {
  const step = [...(goal?.steps ?? [])]
    .reverse()
    .find((item) => item.phase === 'thinking' && item.reasoning)

  if (!step) return null

  return (
    <article className="agent-runtime-card thinking-card" data-testid="agent-thinking-card">
      <header>
        <span className="agent-runtime-icon" aria-hidden="true">✦</span>
        <div>
          <span className="eyebrow">Thinking</span>
          <strong>{step.title}</strong>
        </div>
        <span className={`agent-phase-pill ${step.status}`}>{step.status}</span>
      </header>
      <p>{step.reasoning}</p>
      {step.retrieved_context_summary ? (
        <div className="agent-runtime-evidence">
          <span>Retrieved context</span>
          <p>{step.retrieved_context_summary}</p>
        </div>
      ) : null}
    </article>
  )
}
