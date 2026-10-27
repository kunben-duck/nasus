import { useQuery } from '@tanstack/react-query'
import { systemImageApi } from './api'

export function useWorkingImage(projectId: string, sessionId: string) {
  return useQuery({ queryKey: ['system-image', projectId, 'working', sessionId], gcTime: 0, staleTime: 0,
    retry: false, refetchOnWindowFocus: 'always', queryFn: async ({ signal }) => {
      const image = await systemImageApi.getWorkingImage(projectId, signal)
      if (image.project.id !== projectId || image.read_state?.mode !== 'working_draft') throw new Error('Working image scope mismatch')
      return image
    } })
}
