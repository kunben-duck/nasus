import type { QualityLoopStateView } from '../../projectWorkspaceSelectors'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

const qualityStages = ['Scenarios', 'Cases', 'Automation', 'Release']

export function QualityLoopStateCard({ qualityState }: { qualityState?: QualityLoopStateView }) {
  const { t, tx } = useI18n()
  if (!qualityState) return null

  return (
    <div className="quality-loop-state-card" data-testid="quality-loop-state">
      <div>
        <strong>{tx(qualityState.label)}</strong>
        <p>{t('Release score {score} · Next tool {tool}', { score: qualityState.releaseScore, tool: qualityState.nextTool })}</p>
      </div>
      <div className="quality-stage-bar" aria-label={t('Quality loop stage')}>
        {qualityStages.map((stage, index) => {
          const active = qualityState.stageIndex >= index + 1
          return (
            <span className={active ? 'active' : ''} key={stage}>
              <i />
              {tx(stage)}
            </span>
          )
        })}
      </div>
      {qualityState.blockers.length ? (
        <div className="quality-blocker-list">
          {qualityState.blockers.map((blocker) => (
            <span key={blocker}>{tx(blocker)}</span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
