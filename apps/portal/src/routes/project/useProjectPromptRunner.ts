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
    if (!text || !project) return

    setPrompt('')
    setIsPromptRunning(true)

    try {
      await projectConversation.sendMessage(text)
      await invalidateProjectWorkspaceQueries(queryClient, project)
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
