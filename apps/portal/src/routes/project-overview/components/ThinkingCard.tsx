import type { AgentGoal } from '../../../domains/agent/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function ThinkingCard({ goal }: { goal?: AgentGoal }) {
  const { t, tx } = useI18n()
  const step = [...(goal?.steps ?? [])]
    .reverse()
    .find((item) => item.phase === 'thinking' && item.reasoning)

  if (!step) return null

  return (
    <article className="agent-runtime-card thinking-card" data-testid="agent-thinking-card">
      <header>
        <span className="agent-runtime-icon" aria-hidden="true">✦</span>
        <div>
          <span className="eyebrow">{t('Thinking')}</span>
          <strong>{tx(step.title)}</strong>
        </div>
        <span className={`agent-phase-pill ${step.status}`}>{tx(step.status)}</span>
      </header>
      <p>{tx(step.reasoning ?? '')}</p>
      {step.retrieved_context_summary ? (
        <div className="agent-runtime-evidence">
          <span>{t('Retrieved context')}</span>
          <p>{tx(step.retrieved_context_summary)}</p>
        </div>
      ) : null}
    </article>
  )
}
