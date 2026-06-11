import { ActionComposer } from './ActionComposer'
import { ChatTimeline } from './ChatTimeline'
import type { AgentGoal, ConversationMessage } from '../features/types'

interface ConversationWorkspaceCardProps {
  title?: string
  placeholder: string
  suggestions?: string[]
  messages: ConversationMessage[]
  agentGoals?: AgentGoal[]
  onSubmit: (value: string) => Promise<unknown> | unknown
  compact?: boolean
}

export function ConversationWorkspaceCard({
  title = 'Conversation',
  placeholder,
  suggestions = [],
  messages,
  agentGoals = [],
  onSubmit,
  compact = false,
}: ConversationWorkspaceCardProps) {
  return (
    <article className="panel-card conversation-panel-card">
      <p className="eyebrow">{title}</p>
      <div className={`conversation-stage ${compact ? 'compact' : ''}`}>
        <ChatTimeline messages={messages} agentGoals={agentGoals} />
      </div>
      <ActionComposer
        placeholder={placeholder}
        suggestions={suggestions}
        onSubmit={onSubmit}
      />
    </article>
  )
}
