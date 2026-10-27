import { useEffect, useState } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import type { QueryClient } from '@tanstack/react-query'

import {
  buildResponseStartsProjectCreation,
  feedbackFromBuildResponse,
  latestAssistantText,
  projectIdFromBuildResponse,
  waitForCreatedProjectFromPrompt,
} from '../../domains/platform/buildProjectResolution'
import type { ConversationController } from '../../domains/agent/useConversation'

export function useBuildPromptRunner({
  buildConversation,
  navigate,
  queryClient,
}: {
  buildConversation: ConversationController
  navigate: NavigateFunction
  queryClient: QueryClient
}) {
  const [prompt, setPrompt] = useState('')
  const [isPromptRunning, setIsPromptRunning] = useState(false)
  const [activePromptTurnId, setActivePromptTurnId] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<{ tone: 'assistant' | 'error'; text: string } | null>(null)

  useEffect(() => {
    if (!isPromptRunning || !activePromptTurnId) return
    const message = buildConversation.conversation?.messages.findLast((item) => (
      item.role === 'assistant' && item.metadata?.turn_id === activePromptTurnId
    ))
    const text = message?.blocks.map((block) => block.text).filter(Boolean).join('\n').trim()
    if (text) setFeedback({ tone: 'assistant', text })
  }, [activePromptTurnId, buildConversation.conversation, isPromptRunning])

  async function runPrompt() {
    const text = prompt.trim()
    if (!text) return
    if (!buildConversation.conversationId) return

    setFeedback(null)
    setActivePromptTurnId(null)
    setPrompt('')
    setIsPromptRunning(true)

    try {
      const accepted = await buildConversation.sendMessage(text)
      setActivePromptTurnId(accepted.turn_id)
      const turn = await buildConversation.waitForTurn(accepted.turn_id)
      const response = turn.result
      if (turn.status === 'failed') {
        throw new Error(turn.error || 'The conversation turn failed.')
      }
      await queryClient.invalidateQueries({ queryKey: ['build'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })

      const projectIdFromToolResult = projectIdFromBuildResponse(response)
      if (projectIdFromToolResult) {
        navigate(`/projects/${encodeURIComponent(projectIdFromToolResult)}`)
        return
      }

      const immediateFeedback = feedbackFromBuildResponse(response)
      if (immediateFeedback) {
        setFeedback({ tone: 'assistant', text: immediateFeedback })
        return
      }

      if (!buildResponseStartsProjectCreation(response)) {
        const refreshedConversation = await buildConversation.refreshConversation()
        setFeedback({
          tone: 'assistant',
          text: latestAssistantText(refreshedConversation) ?? 'Nasus completed the request, but no project was created.',
        })
        return
      }

      const created = await waitForCreatedProjectFromPrompt(queryClient, text)
      if (created?.id) {
        navigate(`/projects/${encodeURIComponent(created.id)}`)
        return
      }
      const refreshedConversation = await buildConversation.refreshConversation()
      setFeedback({
        tone: 'assistant',
        text: latestAssistantText(refreshedConversation) ?? 'Nasus completed the request, but no project was created.',
      })
    } catch (error) {
      setPrompt(text)
      setFeedback({
        tone: 'error',
        text: error instanceof Error ? error.message : 'Unable to process the build request.',
      })
    } finally {
      setIsPromptRunning(false)
    }
  }

  async function stopPrompt() {
    await buildConversation.cancelActiveTurn()
    setIsPromptRunning(false)
  }

  return {
    prompt,
    setPrompt,
    runPrompt,
    isPromptRunning,
    stopPrompt,
    feedback,
  }
}
