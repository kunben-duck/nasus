import type { QueryClient } from '@tanstack/react-query'

import type { ProjectCard } from './types'

export async function invalidateProjectWorkspaceQueries(
  queryClient: QueryClient,
  activeProject: ProjectCard,
  conversationId?: string | null,
) {
  await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  await queryClient.invalidateQueries({ queryKey: ['build'] })
  await queryClient.invalidateQueries({ queryKey: ['project', activeProject.id] })
  await queryClient.invalidateQueries({ queryKey: ['system-image', activeProject.id] })
  await queryClient.invalidateQueries({ queryKey: ['conversation-scope', 'project', activeProject.id] })
  if (conversationId) {
    await queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
  }
  await queryClient.invalidateQueries({ queryKey: ['conversation'] })
}
