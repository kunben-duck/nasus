export interface PromptHistoryCursor {
  entries: readonly string[]
  index: number
  draft: string
  value: string
}

export function recallPrompt(
  cursor: PromptHistoryCursor | null,
  history: readonly string[],
  value: string,
  direction: 'older' | 'newer',
): { cursor: PromptHistoryCursor | null; value: string } | null {
  const entries = history.filter((text) => text.trim()).slice(-5)
  if (!entries.length) return null
  if (cursor?.value !== value || cursor.entries.length !== entries.length
    || cursor.entries.some((text, index) => text !== entries[index])) cursor = null
  if (!cursor && direction === 'newer') return null
  const draft = cursor?.draft ?? value
  const index = Math.max(0, Math.min(entries.length, (cursor?.index ?? entries.length) + (direction === 'older' ? -1 : 1)))
  if (index === entries.length) return { cursor: null, value: draft }
  return { cursor: { entries, index, draft, value: entries[index] }, value: entries[index] }
}

export function canRecallPrompt(key: string, value: string, start: number, end: number, browsing: boolean) {
  if (start !== end) return false
  // Recalled multiline entries remain browsable at their restored caret position.
  if (browsing && end === value.length) return true
  return key === 'ArrowUp' ? !value.slice(0, start).includes('\n') : !value.slice(end).includes('\n')
}
