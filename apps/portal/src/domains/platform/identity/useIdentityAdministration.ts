import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { platformApi } from '../api'
import type { AccountStatus, GlobalRole, UserProfile } from '../types'


const identityKeys = {
  sessions: ['identity', 'sessions'] as const,
  users: ['identity', 'users'] as const,
}

export function useIdentityAdministration(user?: UserProfile | null) {
  const queryClient = useQueryClient()
  const sessions = useQuery({
    queryKey: identityKeys.sessions,
    queryFn: platformApi.listMySessions,
    enabled: Boolean(user),
    staleTime: 30_000,
  })
  const users = useQuery({
    queryKey: identityKeys.users,
    queryFn: () => platformApi.listUsers(),
    enabled: user?.role === 'platform_admin',
    staleTime: 30_000,
  })
  const revokeSession = useMutation({
    mutationFn: platformApi.revokeMySession,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: identityKeys.sessions }),
  })
  const updateUser = useMutation({
    mutationFn: ({
      userId,
      payload,
    }: {
      userId: string
      payload: { role?: GlobalRole; status?: AccountStatus }
    }) => platformApi.updateUser(userId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: identityKeys.users }),
  })

  return {
    sessions: sessions.data ?? [],
    users: users.data?.items ?? [],
    loading: sessions.isLoading || users.isLoading,
    pending: revokeSession.isPending || updateUser.isPending,
    error: sessions.error ?? users.error ?? revokeSession.error ?? updateUser.error,
    revokeSession: (sessionId: string) => revokeSession.mutateAsync(sessionId),
    updateRole: (userId: string, role: GlobalRole) => updateUser.mutateAsync({ userId, payload: { role } }),
    updateStatus: (userId: string, status: AccountStatus) => updateUser.mutateAsync({ userId, payload: { status } }),
  }
}
