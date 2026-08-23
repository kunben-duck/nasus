import { useState } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import type { QueryClient } from '@tanstack/react-query'

import {
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

  async function runPrompt() {
    const text = prompt.trim()
    if (!text) return
    if (!buildConversation.conversationId) return

    setPrompt('')
    setIsPromptRunning(true)

    try {
      const response = await buildConversation.sendMessage(text)
      await queryClient.invalidateQueries({ queryKey: ['build'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })

      const projectIdFromToolResult = projectIdFromBuildResponse(response)
      if (projectIdFromToolResult) {
        navigate(`/projects/${encodeURIComponent(projectIdFromToolResult)}`)
        return
      }

      const created = await waitForCreatedProjectFromPrompt(queryClient, text)
      if (created?.id) {
        navigate(`/projects/${encodeURIComponent(created.id)}`)
      }
    } finally {
      setIsPromptRunning(false)
    }
  }

  return {
    prompt,
    setPrompt,
    runPrompt,
    isPromptRunning,
  }
}
