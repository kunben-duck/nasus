import type { QualityLoopStateView } from '../../projectWorkspaceSelectors'

const qualityStages = ['Scenarios', 'Cases', 'Automation', 'Release']

export function QualityLoopStateCard({ qualityState }: { qualityState?: QualityLoopStateView }) {
  if (!qualityState) return null

  return (
    <div className="quality-loop-state-card" data-testid="quality-loop-state">
      <div>
        <strong>{qualityState.label}</strong>
        <p>
          Release score {qualityState.releaseScore} · Next tool {qualityState.nextTool}
        </p>
      </div>
      <div className="quality-stage-bar" aria-label="Quality loop stage">
        {qualityStages.map((stage, index) => {
          const active = qualityState.stageIndex >= index + 1
          return (
            <span className={active ? 'active' : ''} key={stage}>
              <i />
              {stage}
            </span>
          )
        })}
      </div>
      {qualityState.blockers.length ? (
        <div className="quality-blocker-list">
          {qualityState.blockers.map((blocker) => (
            <span key={blocker}>{blocker}</span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
