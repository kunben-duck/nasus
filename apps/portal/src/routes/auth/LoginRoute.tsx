import type { FormEvent } from 'react'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { useAuthActions } from '../../domains/platform/useAuthSession'
import { useI18n } from '../../shared/i18n/I18nProvider'
import { AuthLayout } from './AuthLayout'

type LocationState = {
  from?: { pathname?: string }
  expired?: boolean
}

export function LoginRoute() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuthActions()
  const { t, tx } = useI18n()
  const state = location.state as LocationState | null
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(state?.expired ? t('Your session expired. Sign in again.') : null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login({ email, password })
      navigate(state?.from?.pathname || '/build', { replace: true })
    } catch (exc) {
      setError(exc instanceof Error ? tx(exc.message) : t('Unable to sign in.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout
      eyebrow={t('Welcome back')}
      title={t('Sign in to Nasus Studio')}
      subtitle={t('Continue your agent-first quality workspace, inspect project progress, and keep every action traceable through tools.')}
      action={<Link className="auth-top-button" to="/register">{t('Create account')}</Link>}
    >
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card-header">
          <span className="auth-card-kicker">{t('Email account')}</span>
          <h2>{t('Log in')}</h2>
        </div>
        <label>
          <span>{t('Email')}</span>
          <input autoComplete="email" inputMode="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          <span>{t('Password')}</span>
          <input autoComplete="current-password" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error ? <div className="auth-error" role="alert">{error}</div> : null}
        <button className="auth-primary auth-submit" disabled={submitting} type="submit">
          {submitting ? t('Signing in...') : t('Sign in')}
        </button>
        <p className="auth-footnote">
          {t('New to Nasus?')} <Link to="/register">{t('Create an account with email')}</Link>
        </p>
      </form>
    </AuthLayout>
  )
}
