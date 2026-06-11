import type { AgentGoal, ConversationMessage } from '../features/types'

export function ChatTimeline({
  messages,
  agentGoals = [],
}: {
  messages: ConversationMessage[]
  agentGoals?: AgentGoal[]
}) {
  return (
    <section className="timeline">
      {messages.map((message) => (
        <article className={`message-card ${message.role}`} key={message.id}>
          <div className="message-role">{message.role === 'assistant' ? 'Nasus Agent' : 'You'}</div>
          {message.blocks.map((block, index) => (
            <p className="message-text" key={`${message.id}:${index}`}>
              {block.text}
            </p>
          ))}
        </article>
      ))}
      {agentGoals.map((goal) => (
        <article className="agent-goal-card" key={goal.id}>
          <div className="agent-goal-header">
            <div>
              <p className="eyebrow">Agent Goal</p>
              <h3>{goal.title}</h3>
            </div>
            <span className={`status-badge ${goal.status}`}>{goal.status}</span>
          </div>
          <p className="message-text">{goal.summary}</p>
          <div className="goal-steps">
            {goal.steps.map((step) => (
              <div className={`goal-step ${step.status}`} key={step.id}>
                <span>{step.title}</span>
                <strong>{step.status}</strong>
              </div>
            ))}
          </div>
        </article>
      ))}
    </section>
  )
}

