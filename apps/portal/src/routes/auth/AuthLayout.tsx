import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { AuthParticleField } from './AuthParticles'
import { useInteractiveParticles } from './useInteractiveParticles'

export function AuthLayout({
  eyebrow,
  title,
  subtitle,
  action,
  children,
}: {
  eyebrow: string
  title: string
  subtitle: string
  action?: ReactNode
  children: ReactNode
}) {
  const particleHandlers = useInteractiveParticles()

  return (
    <main className="auth-shell welcome-shell ai-welcome-shell auth-landing-shell" {...particleHandlers}>
      <AuthParticleField className="welcome-particles ai-welcome-stars" count={240} />
      <header className="auth-header ai-welcome-header">
        <Link className="auth-brand ai-welcome-brand" to="/welcome">
          <img src="/nasus.png" alt="Nasus" />
          <span>Nasus Studio</span>
        </Link>
        <nav className="ai-welcome-nav" aria-label="Nasus product modules">
          <Link to="/welcome#system-image">System image</Link>
          <Link to="/welcome#agent-first">Agent-first</Link>
          <Link to="/welcome#quality-loop">Quality loop</Link>
        </nav>
        {action}
      </header>
      <section className="auth-landing-hero">
        <div className="auth-landing-copy">
          <span className="auth-eyebrow">{eyebrow}</span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        {children}
      </section>
    </main>
  )
}
