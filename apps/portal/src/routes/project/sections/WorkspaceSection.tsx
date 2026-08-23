import type { ProjectRouteContext } from '../ProjectRouteTypes'
import { AgentConversationPanel } from './primitives/AgentConversationPanel'

export function WorkspaceSection({ context, usId }: { context: ProjectRouteContext; usId?: string }) {
  const usItem = context.workspace?.us_items.find((item) => item.id === usId) ?? context.workspace?.us_items[0]
  const lanes = context.workspace?.asset_lanes ?? []

  return (
    <>
      <div className="agent-heading">
        <h1>{usItem?.title ?? 'Personal Workspace'}</h1>
        <div className="segmented">
          <button className="active">Assets</button>
          <button>Agent</button>
          <button>Runs</button>
        </div>
      </div>
      <div className="quality-asset-panel">
        <div className="quality-panel-header">
          <div>
            <span className="eyebrow">Quality asset pack</span>
            <strong>{usItem?.id ?? 'US'} · {usItem?.status ?? 'not started'}</strong>
            <p>{usItem?.next_action ?? 'Ask Nasus to generate scenarios, cases, automation, and release evidence.'}</p>
          </div>
          {usItem ? <span className={`quality-state-pill ${usItem.risk}`}>{usItem.risk}</span> : null}
        </div>
        <div className="quality-lane-grid">
          {lanes.map((lane) => (
            <div className={`quality-lane-card ${lane.status}`} key={lane.id}>
              <div>
                <span className="quality-lane-dot" />
                <strong>{lane.label}</strong>
              </div>
              <p>{lane.summary}</p>
              <span>{lane.status}</span>
            </div>
          ))}
        </div>
      </div>
      <AgentConversationPanel context={context} placeholder="Generate, review, or revise quality assets for this US" />
    </>
  )
}
