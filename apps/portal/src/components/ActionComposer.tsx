import { useState } from 'react'
import type { FormEvent } from 'react'

interface ActionComposerProps {
  placeholder: string
  suggestions?: string[]
  onSubmit: (value: string) => Promise<unknown> | unknown
}

export function ActionComposer({
  placeholder,
  suggestions = [],
  onSubmit,
}: ActionComposerProps) {
  const [value, setValue] = useState('')
  const [isSending, setIsSending] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    setIsSending(true)
    try {
      await onSubmit(trimmed)
      setValue('')
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="composer-shell">
      {suggestions.length > 0 ? (
        <div className="suggestion-row">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              className="suggestion-chip"
              type="button"
              onClick={() => setValue(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}
      <form className="composer" onSubmit={handleSubmit}>
        <textarea
          className="input-textarea"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={placeholder}
          rows={3}
        />
        <button className="primary-button send-btn" data-action="composer_send" type="submit" disabled={isSending}>
          {isSending ? 'Working…' : 'Send'}
        </button>
      </form>
    </div>
  )
}
