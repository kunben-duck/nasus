import type { ProjectRouteContext } from '../ProjectRouteTypes'
import type { GovernanceApprovalCardView } from '../ProjectSectionViewModels'
import { governanceSectionModel } from '../ProjectSectionViewModels'

export function GovernanceSection({ context, approvalId }: { context: ProjectRouteContext; approvalId?: string }) {
  const { approvals, selected } = governanceSectionModel(context, approvalId)

  return (
    <>
      <div className="agent-heading">
        <h1>Governance</h1>
        <div className="segmented">
          <button className="active">Pending</button>
          <button>Resolved</button>
          <button>Policy</button>
        </div>
      </div>
      <div className="confirmation-gate-card">
        <div>
          <span className="confirmation-kicker">Approval rail</span>
          <strong>{selected?.title ?? 'No approval waiting'}</strong>
          <p>{selected?.summary ?? 'High-risk tools pause here for confirmation, approval, or policy gates.'}</p>
        </div>
        <button className="composer-action-button build-submit-button" disabled={!selected}>
          Review gate
        </button>
      </div>
      <div className="quality-lane-grid">
        {approvals.map((approval) => (
          <ApprovalCard approval={approval} key={approval.id} />
        ))}
      </div>
    </>
  )
}

function ApprovalCard({ approval }: { approval: GovernanceApprovalCardView }) {
  return (
    <div className={`quality-lane-card ${approval.status}`}>
      <div>
        <span className="quality-lane-dot" />
        <strong>{approval.title}</strong>
      </div>
      <p>{approval.summary}</p>
      <span>{approval.status}</span>
    </div>
  )
}
