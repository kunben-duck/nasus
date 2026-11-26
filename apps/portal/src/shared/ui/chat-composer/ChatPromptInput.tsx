import { useRef } from 'react'
import { useI18n } from '../../i18n/I18nProvider'
import { canRecallPrompt, recallPrompt, type PromptHistoryCursor } from './promptHistory'

export function ChatPromptInput({
  prompt,
  setPrompt,
  runPrompt,
  busy,
  promptHistory = [],
  placeholder,
  testId,
  disabled = false,
}: {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  busy: boolean
  promptHistory?: readonly string[]
  placeholder: string
  testId: string
  disabled?: boolean
}) {
  const { t } = useI18n()
  const historyCursor = useRef<PromptHistoryCursor | null>(null)
  return (
    <textarea
      data-testid={testId}
      disabled={disabled}
      value={prompt}
      onChange={(event) => {
        historyCursor.current = null
        setPrompt(event.target.value)
      }}
      onPointerDown={() => { historyCursor.current = null }}
      placeholder={placeholder}
      aria-label={placeholder}
      title={t('Enter to send, Shift+Enter for a new line; Up/Down to recall the last 5 inputs')}
      aria-keyshortcuts="Enter ArrowUp ArrowDown"
      onKeyDown={(event) => {
        // Some IMEs report the committing Enter as keyCode 229, not isComposing.
        if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
          if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return
          const input = event.currentTarget
          if (!canRecallPrompt(event.key, prompt, input.selectionStart, input.selectionEnd,
            historyCursor.current?.value === prompt)) return
          const recalled = recallPrompt(historyCursor.current, promptHistory, prompt, event.key === 'ArrowUp' ? 'older' : 'newer')
          if (!recalled) return
          event.preventDefault()
          historyCursor.current = recalled.cursor
          setPrompt(recalled.value)
          requestAnimationFrame(() => {
            if (document.activeElement === input && input.value === recalled.value) {
              input.setSelectionRange(recalled.value.length, recalled.value.length)
            }
          })
          return
        }
        if (event.key !== 'Enter' || event.shiftKey) return
        event.preventDefault()
        if (!event.repeat && !busy && prompt.trim()) {
          historyCursor.current = null
          runPrompt()
        }
      }}
    />
  )
}
