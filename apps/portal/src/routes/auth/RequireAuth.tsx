import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { clearAuthSession, hasAuthToken, useAuthUser } from '../../domains/platform/useAuthSession'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function RequireAuth() {
  const { t } = useI18n()
  const location = useLocation()
  const token = hasAuthToken()
  const userQuery = useAuthUser()

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (userQuery.isError) {
    clearAuthSession()
    return <Navigate to="/login" replace state={{ from: location, expired: true }} />
  }

  if (userQuery.isPending) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-mark">
          <img src="/nasus.png" alt="Nasus" />
        </div>
        <span>{t('Preparing Nasus workspace...')}</span>
      </div>
    )
  }

  return <Outlet />
}
