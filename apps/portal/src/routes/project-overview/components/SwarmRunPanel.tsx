import type { AgentSwarmRun } from '../../../domains/agent/types'

export function SwarmRunPanel({ swarms }: { swarms: AgentSwarmRun[] }) {
  const visible = swarms.slice(-2).reverse()
  if (!visible.length) return null

  return (
    <section className="swarm-run-panel" data-testid="agent-swarm-run-panel">
      <div className="agent-loop-trace-header">
        <span className="eyebrow">Agent swarm</span>
        <strong>Parallel candidate analysis</strong>
      </div>
      {visible.map((swarm) => {
        const completed = swarm.assignments.filter((assignment) => assignment.status === 'completed').length
        return (
          <article className={`agent-runtime-card swarm-run-card ${swarm.status}`} key={swarm.id}>
            <header>
              <span className="agent-runtime-icon swarm" aria-hidden="true">⌘</span>
              <div>
                <span className="eyebrow">{swarm.swarm_kind}</span>
                <strong>{swarm.result_summary}</strong>
              </div>
              <span className={`agent-goal-status ${swarm.status}`}>{swarm.status.replaceAll('_', ' ')}</span>
            </header>
            <div className="swarm-progress-track" aria-label={`${completed} of ${swarm.assignments.length} assignments completed`}>
              <span style={{ width: `${swarm.assignments.length ? (completed / swarm.assignments.length) * 100 : 0}%` }} />
            </div>
            <div className="swarm-assignment-grid">
              {swarm.assignments.map((assignment) => (
                <div className={`swarm-assignment ${assignment.status}`} key={assignment.id}>
                  <span>{assignment.worker_agent_kind}</span>
                  <strong>{assignment.status}</strong>
                  <p>{assignment.summary}</p>
                </div>
              ))}
            </div>
          </article>
        )
      })}
    </section>
  )
}
