import type { ProjectRouteContext } from '../../ProjectRouteTypes'

export function AgentConversationPanel({ context, placeholder }: { context: ProjectRouteContext; placeholder: string }) {
  return (
    <>
      <div className="agent-log">
        {context.messages.slice(-5).map((message, index) => (
          <div className={`message-row ${message.role}`} key={`${message.role}-${message.text}-${index}`}>
            <span>{message.role === 'user' ? 'You' : message.role === 'tool' ? 'Tool' : 'Nasus'}</span>
            <p>{message.text}</p>
          </div>
        ))}
      </div>
      <div className="task-composer">
        <textarea
          value={context.prompt}
          onChange={(event) => context.setPrompt(event.target.value)}
          placeholder={placeholder}
          disabled={context.loading}
        />
        <div className="task-chip-row">
          <button className="tool-chip active" disabled={context.loading}>
            Tools ×
          </button>
          <button className="round-icon" onClick={context.runPrompt} disabled={context.loading}>
            ↵
          </button>
        </div>
      </div>
    </>
  )
}
