import type { FormEvent } from 'react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuthActions } from '../../domains/platform/useAuthSession'
import { AuthLayout } from './AuthLayout'

export function RegisterRoute() {
  const navigate = useNavigate()
  const { register } = useAuthActions()
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
      setError('Passwords do not match.')
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
      setError(exc instanceof Error ? exc.message : 'Unable to create account.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout
      eyebrow="Start with email"
      title="Create your Nasus account"
      subtitle="Create a quality workspace with a QA lead account. Project-level access is granted when you create or join a project."
      action={<Link className="auth-top-button" to="/login">Sign in</Link>}
    >
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card-header">
          <span className="auth-card-kicker">QA lead account</span>
          <h2>Register</h2>
        </div>
        <label>
          <span>Name</span>
          <input autoComplete="name" placeholder="Optional" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          <span>Email</span>
          <input autoComplete="email" inputMode="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          <span>Password</span>
          <input autoComplete="new-password" minLength={8} required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <label>
          <span>Confirm password</span>
          <input autoComplete="new-password" minLength={8} required type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
        </label>
        {error ? <div className="auth-error" role="alert">{error}</div> : null}
        <button className="auth-primary auth-submit" disabled={submitting} type="submit">
          {submitting ? 'Creating account...' : 'Create account'}
        </button>
        <p className="auth-footnote">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </AuthLayout>
  )
}
