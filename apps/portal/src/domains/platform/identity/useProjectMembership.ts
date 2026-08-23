import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { platformApi } from '../api'
import type { ProjectRole } from '../types'


const memberKey = (projectId: string) => ['project', projectId, 'members'] as const

export function useProjectMembership(projectId: string, candidateQuery: string) {
  const queryClient = useQueryClient()
  const members = useQuery({
    queryKey: memberKey(projectId),
    queryFn: () => platformApi.listProjectMembers(projectId),
    enabled: Boolean(projectId),
    staleTime: 30_000,
  })
  const normalizedQuery = candidateQuery.trim()
  const candidates = useQuery({
    queryKey: ['project', projectId, 'member-candidates', normalizedQuery],
    queryFn: () => platformApi.searchProjectMemberCandidates(projectId, normalizedQuery),
    enabled: Boolean(projectId) && normalizedQuery.length >= 2,
    staleTime: 15_000,
  })
  const upsert = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: ProjectRole }) =>
      platformApi.upsertProjectMember(projectId, userId, role),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: memberKey(projectId) })
      await queryClient.invalidateQueries({ queryKey: ['project', projectId, 'member-candidates'] })
    },
  })
  const revoke = useMutation({
    mutationFn: (userId: string) => platformApi.revokeProjectMember(projectId, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: memberKey(projectId) }),
  })

  return {
    members: members.data ?? [],
    candidates: candidates.data ?? [],
    loading: members.isLoading,
    searching: candidates.isFetching,
    pending: upsert.isPending || revoke.isPending,
    error: members.error ?? candidates.error ?? upsert.error ?? revoke.error,
    assign: (userId: string, role: ProjectRole = 'tester') => upsert.mutateAsync({ userId, role }),
    changeRole: (userId: string, role: ProjectRole) => upsert.mutateAsync({ userId, role }),
    revoke: (userId: string) => revoke.mutateAsync(userId),
  }
}
