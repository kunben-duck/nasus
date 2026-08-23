export const agentCards = [
  {
    title: 'System Image Builder',
    icon: '✦',
    tone: 'gold',
    copy: 'Builds and updates the project baseline from code, historical US docs, and test assets.',
  },
  {
    title: 'Quality Loop Agent',
    icon: '⌁',
    tone: 'green',
    copy: 'Plans scenarios, cases, execution, failure analysis, and release readiness from one goal.',
  },
  {
    title: 'Release Assessor',
    icon: '◇',
    tone: 'blue',
    copy: 'Scores go-live quality using evidence, open risks, run results, and governance state.',
  },
  {
    title: 'Repo Maintainer',
    icon: '⌘',
    tone: 'purple',
    copy: 'Reads code impact, maps changed modules to US scope, and proposes test coverage deltas.',
  },
] as const

export type AgentCardTitle = typeof agentCards[number]['title']
