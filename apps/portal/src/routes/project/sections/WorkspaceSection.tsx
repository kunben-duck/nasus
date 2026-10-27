import type { ProjectRouteContext } from '../ProjectRouteTypes'
import { AgentConversationPanel } from './primitives/AgentConversationPanel'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function WorkspaceSection({ context, usId }: { context: ProjectRouteContext; usId?: string }) {
  const { t, tx } = useI18n()
  const usItem = context.workspace?.us_items.find((item) => item.id === usId) ?? context.workspace?.us_items[0]
  const lanes = context.workspace?.asset_lanes ?? []

  return (
    <>
      <div className="agent-heading">
        <h1>{usItem?.title ? tx(usItem.title) : t('Personal Workspace')}</h1>
        <div className="segmented">
          <button className="active">{t('Assets')}</button>
          <button>{t('Agent')}</button>
          <button>{t('Runs')}</button>
        </div>
      </div>
      <div className="quality-asset-panel">
        <div className="quality-panel-header">
          <div>
            <span className="eyebrow">{t('Quality asset pack')}</span>
            <strong>{usItem?.id ?? 'US'} · {tx(usItem?.status ?? 'not started')}</strong>
            <p>{usItem?.next_action ? tx(usItem.next_action) : t('Ask Nasus to generate scenarios, cases, automation, and release evidence.')}</p>
          </div>
          {usItem ? <span className={`quality-state-pill ${usItem.risk}`}>{tx(usItem.risk)}</span> : null}
        </div>
        <div className="quality-lane-grid">
          {lanes.map((lane) => (
            <div className={`quality-lane-card ${lane.status}`} key={lane.id}>
              <div>
                <span className="quality-lane-dot" />
                <strong>{tx(lane.label)}</strong>
              </div>
              <p>{tx(lane.summary)}</p>
              <span>{tx(lane.status)}</span>
            </div>
          ))}
        </div>
      </div>
      <AgentConversationPanel context={context} placeholder={t('Generate, review, or revise quality assets for this US')} />
    </>
  )
}
