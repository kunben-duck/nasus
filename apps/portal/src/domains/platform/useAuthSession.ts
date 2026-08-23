import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  clearApiAuthToken,
  hasStoredApiAuthToken,
  platformApiAuthToken,
  setApiAuthToken,
} from './authTokenStorage'
import { platformApi } from './api'
import type { AuthLoginPayload, AuthRegisterPayload, AuthSession, UserProfile } from './types'

export const authUserQueryKey = ['auth', 'me'] as const

export function hasAuthToken(): boolean {
  return Boolean(platformApiAuthToken())
}

export function useAuthUser() {
  return useQuery({
    queryKey: authUserQueryKey,
    queryFn: platformApi.authMe,
    enabled: hasAuthToken(),
    retry: false,
    staleTime: 60_000,
  })
}

export function persistAuthSession(session: AuthSession): void {
  setApiAuthToken(session.access_token)
}

export function clearAuthSession(): void {
  clearApiAuthToken()
}

export function useAuthActions() {
  const queryClient = useQueryClient()

  function setSession(session: AuthSession) {
    persistAuthSession(session)
    queryClient.setQueryData(authUserQueryKey, session.user)
    return session
  }

  return {
    hasStoredToken: hasStoredApiAuthToken,
    setSession,
    async login(payload: AuthLoginPayload) {
      return setSession(await platformApi.login(payload))
    },
    async register(payload: AuthRegisterPayload) {
      return setSession(await platformApi.register(payload))
    },
    setUser(user: UserProfile) {
      queryClient.setQueryData(authUserQueryKey, user)
    },
    clearSession() {
      clearAuthSession()
      queryClient.removeQueries({ queryKey: authUserQueryKey })
    },
  }
}
