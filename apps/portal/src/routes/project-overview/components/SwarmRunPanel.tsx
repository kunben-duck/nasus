import type { AgentSwarmRun } from '../../../domains/agent/types'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function SwarmRunPanel({ swarms }: { swarms: AgentSwarmRun[] }) {
  const { t, tx } = useI18n()
  const visible = swarms.slice(-2).reverse()
  if (!visible.length) return null

  return (
    <section className="swarm-run-panel" data-testid="agent-swarm-run-panel">
      <div className="agent-loop-trace-header">
        <span className="eyebrow">{t('Agent swarm')}</span>
        <strong>{t('Parallel candidate analysis')}</strong>
      </div>
      {visible.map((swarm) => {
        const completed = swarm.assignments.filter((assignment) => assignment.status === 'completed').length
        return (
          <article className={`agent-runtime-card swarm-run-card ${swarm.status}`} key={swarm.id}>
            <header>
              <span className="agent-runtime-icon swarm" aria-hidden="true">⌘</span>
              <div>
                <span className="eyebrow">{tx(swarm.swarm_kind)}</span>
                <strong>{tx(swarm.result_summary)}</strong>
              </div>
              <span className={`agent-goal-status ${swarm.status}`}>{tx(swarm.status.replaceAll('_', ' '))}</span>
            </header>
            <div className="swarm-progress-track" aria-label={t('{completed} of {total} assignments completed', { completed, total: swarm.assignments.length })}>
              <span style={{ width: `${swarm.assignments.length ? (completed / swarm.assignments.length) * 100 : 0}%` }} />
            </div>
            <div className="swarm-assignment-grid">
              {swarm.assignments.map((assignment) => (
                <div className={`swarm-assignment ${assignment.status}`} key={assignment.id}>
                  <span>{tx(assignment.worker_agent_kind)}</span>
                  <strong>{tx(assignment.status)}</strong>
                  <p>{tx(assignment.summary)}</p>
                </div>
              ))}
            </div>
          </article>
        )
      })}
    </section>
  )
}
