import type { ReactNode } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { ChatPromptInput } from './ChatPromptInput'

export function AgentComposer({ prompt, promptHistory, setPrompt, runPrompt, stopPrompt, disabled, streaming, placeholder, children }: {
  prompt: string
  promptHistory: readonly string[]
  setPrompt: (value: string) => void
  runPrompt: () => void
  stopPrompt: () => void
  disabled: boolean
  streaming: boolean
  placeholder: string
  children: ReactNode
}) {
  const { t } = useI18n()
  const label = streaming ? t('Stop') : t('Send message')
  return <div className="task-composer">
    <ChatPromptInput testId="project-agent-input" placeholder={placeholder}
      prompt={prompt} promptHistory={promptHistory} setPrompt={setPrompt}
      runPrompt={runPrompt} disabled={disabled} busy={disabled || streaming} />
    <div className="agent-composer-footer">
      <div className="task-chip-row">{children}</div>
      <button type="button" className="agent-composer-send" data-testid={streaming ? 'project-agent-stop' : 'project-agent-submit'}
        aria-label={label} title={label} disabled={!streaming && (disabled || !prompt.trim())}
        onClick={streaming ? stopPrompt : runPrompt}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor"
          strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          {streaming ? <rect x="6" y="6" width="12" height="12" rx="2" />
            : <path d="M12 19V5m-6 6 6-6 6 6" />}
        </svg>
      </button>
    </div>
  </div>
}
