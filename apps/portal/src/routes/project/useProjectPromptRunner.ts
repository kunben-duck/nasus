import { useState } from 'react'

import type { QueryClient } from '@tanstack/react-query'

import { invalidateProjectWorkspaceQueries } from '../../domains/platform/projectWorkspaceInvalidation'
import type { ProjectCard } from '../../domains/platform/types'
import type { ProjectConversationController } from './useProjectConversationModel'

export function useProjectPromptRunner({
  project,
  projectConversation,
  queryClient,
}: {
  project?: ProjectCard
  projectConversation: ProjectConversationController
  queryClient: QueryClient
}) {
  const [prompt, setPrompt] = useState('')
  const [isPromptRunning, setIsPromptRunning] = useState(false)

  async function runPrompt() {
    const text = prompt.trim()
    if (!text || !project || !projectConversation.conversationId || projectConversation.isLoading
      || projectConversation.isSending || isPromptRunning) return

    setPrompt('')
    setIsPromptRunning(true)

    try {
      const accepted = await projectConversation.sendMessage(text)
      await projectConversation.waitForTurn(accepted.turn_id)
      await invalidateProjectWorkspaceQueries(queryClient, project)
    } finally {
      setIsPromptRunning(false)
    }
  }

  async function stopPrompt() {
    await projectConversation.cancelActiveTurn()
    setIsPromptRunning(false)
  }

  return {
    prompt,
    setPrompt,
    runPrompt,
    stopPrompt,
    isPromptRunning,
  }
}
