import type { QueryClient } from '@tanstack/react-query'

import { invalidateProjectWorkspaceQueries } from '../../domains/platform/projectWorkspaceInvalidation'
import type { ProjectCard } from '../../domains/platform/types'
import { useToolInvocationConfirmation as usePlatformToolInvocationConfirmation } from '../../domains/platform/useToolInvocationConfirmation'
import type { ProjectActionLockController } from './useProjectActionLock'

export function useProjectToolConfirmation({
  project,
  queryClient,
  projectActionLock,
}: {
  project?: ProjectCard
  queryClient: QueryClient
  projectActionLock: ProjectActionLockController
}) {
  const toolInvocationConfirmation = usePlatformToolInvocationConfirmation({
    onConfirmed: async () => {
      if (!project) return
      await invalidateProjectWorkspaceQueries(queryClient, project)
    },
  })

  async function confirmToolInvocation(invocationId: string) {
    await projectActionLock.runLockedAction(`tool-confirm:${invocationId}`, async () => {
      await toolInvocationConfirmation.confirmToolInvocation(invocationId)
    })
  }

  return {
    confirmToolInvocation,
    isConfirmingToolInvocation: toolInvocationConfirmation.isConfirmingToolInvocation,
  }
}
