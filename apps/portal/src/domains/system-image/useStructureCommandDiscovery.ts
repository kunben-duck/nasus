import { useInfiniteQuery } from '@tanstack/react-query'
import type { BuildPlan } from './types/buildPlan'
import type { ImageReadScope } from './useImageRevisions'
import { structureCommandDiscoveryApi } from './structureCommandDiscoveryApi'

export function useStructureCommandDiscovery(scope: ImageReadScope, plan: BuildPlan) {
  const query = useInfiniteQuery({
    queryKey: ['system-image', scope.projectId, 'structure-discovery', scope.sessionId, plan.plan_id, plan.plan_digest],
    initialPageParam: '', staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ pageParam, signal }) => structureCommandDiscoveryApi.list(scope.projectId, plan.plan_id, plan.plan_digest, pageParam, signal),
    getNextPageParam: (page) => page.next_after_id ?? undefined,
  })
  return {
    items: query.isError ? [] : query.data?.pages.flatMap((page) => page.items) ?? [],
    ready: query.isSuccess && !query.isFetching, checking: query.isPending || query.isFetching,
    failed: query.isError, hasMore: query.hasNextPage,
    reload: () => query.refetch(), more: () => query.fetchNextPage(),
  }
}
