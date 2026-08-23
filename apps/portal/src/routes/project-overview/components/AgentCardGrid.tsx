import { agentCards, type AgentCardTitle } from './agentCards'

export function AgentCardGrid({
  disabled,
  onCardAction,
}: {
  disabled: boolean
  onCardAction: (title: AgentCardTitle) => void
}) {
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
          <strong>{card.title}</strong>
          <p>{card.copy}</p>
        </button>
      ))}
    </div>
  )
}
