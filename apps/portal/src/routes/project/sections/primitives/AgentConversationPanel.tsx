import type { ProjectRouteContext } from '../../ProjectRouteTypes'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { MarkdownContent } from '../../../../shared/ui/MarkdownContent'
import { AgentComposer } from '../../../../shared/ui/chat-composer/AgentComposer'

export function AgentConversationPanel({ context, placeholder }: { context: ProjectRouteContext; placeholder: string }) {
  const { t } = useI18n()
  return (
    <>
      <div className="agent-log">
        {context.messages.slice(-5).map((message) => (
          <div className={`message-row ${message.role}`} key={message.id}>
            <span>{message.role === 'user' ? t('You') : message.role === 'tool' ? t('Tool') : 'Nasus'}</span>
            <MarkdownContent content={message.text} streaming={message.status === 'streaming'} />
          </div>
        ))}
      </div>
      <AgentComposer key={context.project.id} prompt={context.prompt} promptHistory={context.promptHistory}
        setPrompt={context.setPrompt} runPrompt={context.runPrompt} stopPrompt={context.stopPrompt}
        streaming={context.streaming} disabled={context.loading} placeholder={placeholder}>
        <button className="tool-chip active" disabled={context.loading}>{t('Tools')} ×</button>
      </AgentComposer>
    </>
  )
}
