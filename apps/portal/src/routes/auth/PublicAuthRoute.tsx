import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { hasAuthToken } from '../../domains/platform/useAuthSession'

export function PublicAuthRoute({ children }: { children: ReactNode }) {
  if (hasAuthToken()) {
    return <Navigate to="/build" replace />
  }

  return children
}
