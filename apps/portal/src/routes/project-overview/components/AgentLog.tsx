import type { MessageRow } from '../ProjectWorkspaceTypes'

export function AgentLog({ messages }: { messages: MessageRow[] }) {
  return (
    <div className="agent-log">
      {messages.slice(-5).map((message, index) => (
        <div className={`message-row ${message.role}`} key={`${message.role}-${message.text}-${index}`}>
          <span>{message.role === 'user' ? 'You' : message.role === 'tool' ? 'Tool' : 'Nasus'}</span>
          <p>{message.text}</p>
        </div>
      ))}
    </div>
  )
}
