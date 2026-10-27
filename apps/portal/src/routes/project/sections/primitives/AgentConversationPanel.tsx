import type { ProjectRouteContext } from '../../ProjectRouteTypes'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { MarkdownContent } from '../../../../shared/ui/MarkdownContent'

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
      <div className="task-composer">
        <textarea
          value={context.prompt}
          onChange={(event) => context.setPrompt(event.target.value)}
          placeholder={placeholder}
          disabled={context.loading}
        />
        <div className="task-chip-row">
          <button className="tool-chip active" disabled={context.loading}>
            {t('Tools')} ×
          </button>
          {context.streaming ? (
            <button className="round-icon" onClick={context.stopPrompt} aria-label={t('Stop')}>■</button>
          ) : (
            <button className="round-icon" onClick={context.runPrompt} disabled={context.loading}>↵</button>
          )}
        </div>
      </div>
    </>
  )
}
