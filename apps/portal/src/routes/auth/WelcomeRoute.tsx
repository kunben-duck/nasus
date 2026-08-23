import { Link } from 'react-router-dom'

import { AuthParticleField } from './AuthParticles'
import { useInteractiveParticles } from './useInteractiveParticles'

const welcomeSuggestions = [
  {
    icon: 'account_tree',
    label: 'Initialize system image from code',
    prompt: 'Map code modules, APIs, and core business flows before quality work starts.',
  },
  {
    icon: 'rule',
    label: 'Generate test scope from US',
    prompt: 'Turn a user story into impacted areas, risks, scenarios, and cases.',
  },
  {
    icon: 'verified',
    label: 'Assess release readiness',
    prompt: 'Summarize quality evidence and decide whether a version can be released.',
  },
]

const capabilitySections = [
  {
    id: 'system-image',
    eyebrow: 'System Image',
    title: 'Build on a living system image',
    copy: 'Nasus starts with code and can connect requirements and historical tests into one project baseline. The system image becomes the agent-readable map for every later decision.',
    cards: [
      ['Code graph', 'Index repositories, modules, APIs, data flows, and change impact.'],
      ['US anchors', 'Link requirements to the code and capabilities they describe.'],
      ['Test evidence', 'Connect cases, scripts, runs, and historical failures back to product behavior.'],
    ],
  },
  {
    id: 'agent-first',
    eyebrow: 'Agent-first',
    title: 'Let the main agent operate the platform',
    copy: 'All meaningful actions are exposed as governed tools. Chat, buttons, chips, and cards trigger the same command surface, so users can ask Nasus to plan, execute, inspect, and summarize work.',
    cards: [
      ['Tool-first actions', 'Every create, import, generate, execute, approve, and query action is callable.'],
      ['Context memory', 'Short-term session context and long-term project knowledge guide future work.'],
      ['Governed execution', 'Risky actions require confirmation, approval, or policy gates before changing facts.'],
    ],
  },
  {
    id: 'quality-loop',
    eyebrow: 'Quality Loop',
    title: 'Close the loop from change to release',
    copy: 'Nasus converts system understanding into test scope, cases, automation, execution evidence, failure analysis, and release scoring.',
    cards: [
      ['Test generation', 'Generate scenarios and cases from impacted behavior instead of isolated prompts.'],
      ['Execution evidence', 'Track runs, failures, screenshots, logs, and agent reasoning in one chain.'],
      ['Release scoring', 'Evaluate coverage, unresolved risk, approvals, and readiness before launch.'],
    ],
  },
]

export function WelcomeRoute() {
  const particleHandlers = useInteractiveParticles()

  return (
    <main className="auth-shell welcome-shell ai-welcome-shell" {...particleHandlers}>
      <AuthParticleField className="welcome-particles ai-welcome-stars" count={240} />
      <header className="auth-header ai-welcome-header">
        <Link className="auth-brand ai-welcome-brand" to="/welcome">
          <img src="/nasus.png" alt="Nasus" />
          <span>Nasus Studio</span>
        </Link>
        <nav className="ai-welcome-nav" aria-label="Nasus product modules">
          <a href="#system-image">System image</a>
          <a href="#agent-first">Agent-first</a>
          <a href="#quality-loop">Quality loop</a>
        </nav>
        <Link className="auth-top-button ai-welcome-cta" to="/login">
          <span className="material-symbols-outlined" aria-hidden="true">login</span>
          Get started
        </Link>
      </header>

      <section className="ai-welcome-hero">
        <div className="ai-welcome-hero-copy">
          <span className="auth-eyebrow">Nasus Assurance Studio</span>
          <h1>Build quality project from now</h1>
        </div>
        <Link className="ai-welcome-prompt" to="/login" aria-label="Start Nasus from a quality goal">
          <span className="ai-welcome-placeholder">Describe the quality goal you want Nasus to help with</span>
          <strong>Get started</strong>
        </Link>
        <div className="ai-welcome-suggestions" aria-label="Example quality goals">
          {welcomeSuggestions.map((suggestion) => (
            <Link key={suggestion.label} to="/login">
              <span className="material-symbols-outlined" aria-hidden="true">{suggestion.icon}</span>
              <span>
                <strong>{suggestion.label}</strong>
                <em>{suggestion.prompt}</em>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <div className="ai-welcome-sections">
        {capabilitySections.map((section) => (
          <section className="ai-welcome-section" id={section.id} key={section.id}>
            <span className="auth-eyebrow">{section.eyebrow}</span>
            <div className="ai-welcome-section-heading">
              <h2>{section.title}</h2>
              <p>{section.copy}</p>
            </div>
            <div className="ai-welcome-card-grid">
              {section.cards.map(([title, copy]) => (
                <article className="ai-welcome-card" key={title}>
                  <h3>{title}</h3>
                  <p>{copy}</p>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>

      <footer className="ai-welcome-footer">
        <span>Nasus Studio</span>
        <p>Agent-first quality assurance for the AI coding era.</p>
      </footer>
    </main>
  )
}
