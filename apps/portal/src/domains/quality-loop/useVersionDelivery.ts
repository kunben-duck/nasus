import { useId } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuthUser } from '../platform/useAuthSession'
import { versionDeliveryApi } from './versionDeliveryApi'

const privateRead = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }

export function useDeliveryIterations(projectId: string) {
  const sessionId = useId(), actor = useAuthUser()
  const query = useQuery({ ...privateRead,
    queryKey: ['delivery-iterations', projectId, actor.data?.id, sessionId],
    enabled: !!actor.data && !actor.isError,
    queryFn: ({ signal }) => versionDeliveryApi.list(projectId, signal) })
  return { query, versions: !actor.isError && !query.isFetching && !query.isError ? query.data : undefined }
}

export function useVersionDelivery(projectId: string, versionId: string) {
  const sessionId = useId(), actor = useAuthUser()
  const query = useQuery({ ...privateRead,
    queryKey: ['version-delivery', projectId, actor.data?.id, sessionId, versionId],
    enabled: !!actor.data && !actor.isError && !!versionId,
    queryFn: ({ signal }) => versionDeliveryApi.read(projectId, versionId, signal) })
  return { query, view: !actor.isError && !query.isFetching && !query.isError ? query.data : undefined }
}
