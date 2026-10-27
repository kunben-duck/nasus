import { agentCards, type AgentCardTitle } from './agentCards'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function AgentCardGrid({
  disabled,
  onCardAction,
}: {
  disabled: boolean
  onCardAction: (title: AgentCardTitle) => void
}) {
  const { tx } = useI18n()
  return (
    <div className="agent-card-grid">
      {agentCards.map((card) => (
        <button
          className="agent-card"
          data-testid={`agent-card-${card.title.toLowerCase().replaceAll(' ', '-')}`}
          key={card.title}
          onClick={() => onCardAction(card.title)}
          disabled={disabled}
        >
          <span className={`agent-icon ${card.tone}`}>{card.icon}</span>
          <strong>{tx(card.title)}</strong>
          <p>{tx(card.copy)}</p>
        </button>
      ))}
    </div>
  )
}
