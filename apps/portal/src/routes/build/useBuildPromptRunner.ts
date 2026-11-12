import { useRef, useState } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type { ConversationController } from '../../domains/agent/useConversation'

export function useBuildPromptRunner({ buildConversation, queryClient }: {
  buildConversation: ConversationController
  queryClient: QueryClient
}) {
  const [prompt, setPrompt] = useState('')
  const [isPromptRunning, setIsPromptRunning] = useState(false)
  const [feedback, setFeedback] = useState<{ tone: 'error'; text: string } | null>(null)
  const sending = useRef(false)

  async function sendPrompt(content: string) {
    const text = content.trim()
    if (!text || !buildConversation.conversationId || sending.current) return
    sending.current = true
    setIsPromptRunning(true)
    setFeedback(null)
    setPrompt('')
    try {
      const accepted = await buildConversation.sendMessage(text)
      const turn = await buildConversation.waitForTurn(accepted.turn_id)
      if (turn.status === 'failed') throw new Error(turn.error || 'The conversation turn failed.')
      await buildConversation.refreshConversation()
      void queryClient.invalidateQueries({ queryKey: ['build'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    } catch (error) {
      setPrompt(text)
      setFeedback({ tone: 'error', text: error instanceof Error ? error.message : 'Unable to process the build request.' })
    } finally {
      sending.current = false
      setIsPromptRunning(false)
    }
  }

  async function stopPrompt() {
    await buildConversation.cancelActiveTurn()
  }

  return { prompt, setPrompt, sendPrompt, runPrompt: () => sendPrompt(prompt), isPromptRunning, stopPrompt, feedback }
}
