import type { FormEvent } from 'react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuthActions } from '../../domains/platform/useAuthSession'
import { useI18n } from '../../shared/i18n/I18nProvider'
import { AuthLayout } from './AuthLayout'

export function RegisterRoute() {
  const navigate = useNavigate()
  const { register } = useAuthActions()
  const { t, tx } = useI18n()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    if (password !== confirmPassword) {
      setError(t('Passwords do not match.'))
      return
    }

    setSubmitting(true)
    try {
      await register({
        email,
        password,
        name: name.trim() || undefined,
      })
      navigate('/build', { replace: true })
    } catch (exc) {
      setError(exc instanceof Error ? tx(exc.message) : t('Unable to create account.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout
      eyebrow={t('Start with email')}
      title={t('Create your Nasus account')}
      subtitle={t('Create a quality workspace with a QA lead account. Project-level access is granted when you create or join a project.')}
      action={<Link className="auth-top-button" to="/login">{t('Sign in')}</Link>}
    >
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card-header">
          <span className="auth-card-kicker">{t('QA lead account')}</span>
          <h2>{t('Register')}</h2>
        </div>
        <label>
          <span>{t('Name')}</span>
          <input autoComplete="name" placeholder={t('Optional field')} value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          <span>{t('Email')}</span>
          <input autoComplete="email" inputMode="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          <span>{t('Password')}</span>
          <input autoComplete="new-password" minLength={8} required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <label>
          <span>{t('Confirm password')}</span>
          <input autoComplete="new-password" minLength={8} required type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
        </label>
        {error ? <div className="auth-error" role="alert">{error}</div> : null}
        <button className="auth-primary auth-submit" disabled={submitting} type="submit">
          {submitting ? t('Creating account...') : t('Create account')}
        </button>
        <p className="auth-footnote">
          {t('Already have an account?')} <Link to="/login">{t('Sign in')}</Link>
        </p>
      </form>
    </AuthLayout>
  )
}
