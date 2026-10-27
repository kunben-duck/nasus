import { useI18n } from '../../../shared/i18n/I18nProvider'
import { MarkdownContent } from '../../../shared/ui/MarkdownContent'

export function BuildAgentFeedback({
  feedback,
  streaming,
}: {
  feedback: { tone: 'assistant' | 'error'; text: string } | null
  streaming: boolean
}) {
  const { t } = useI18n()
  if (!feedback) return null

  return (
    <div
      className={`build-agent-feedback ${feedback.tone}`}
      data-testid="build-agent-feedback"
      role={feedback.tone === 'error' ? 'alert' : 'status'}
    >
      <span className="material-symbols-outlined" aria-hidden="true">
        {feedback.tone === 'error' ? 'error' : 'auto_awesome'}
      </span>
      <div>
        <strong>{feedback.tone === 'error' ? t('Build request failed') : 'Nasus'}</strong>
        <MarkdownContent content={feedback.text} streaming={streaming} />
      </div>
    </div>
  )
}
