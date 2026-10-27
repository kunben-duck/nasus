import type { MessageRow } from '../ProjectWorkspaceTypes'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import { MarkdownContent } from '../../../shared/ui/MarkdownContent'

export function AgentLog({ messages }: { messages: MessageRow[] }) {
  const { t } = useI18n()
  return (
    <div className="agent-log">
      {messages.slice(-5).map((message) => (
        <div className={`message-row ${message.role}`} key={message.id}>
          <span>{message.role === 'user' ? t('You') : message.role === 'tool' ? t('Tool') : 'Nasus'}</span>
          <MarkdownContent content={message.text} streaming={message.status === 'streaming'} />
        </div>
      ))}
    </div>
  )
}
