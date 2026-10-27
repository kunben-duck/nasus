import type { ProjectRouteContext } from '../ProjectRouteTypes'
import type { GovernanceApprovalCardView } from '../ProjectSectionViewModels'
import { governanceSectionModel } from '../ProjectSectionViewModels'
import { useI18n } from '../../../shared/i18n/I18nProvider'

export function GovernanceSection({ context, approvalId }: { context: ProjectRouteContext; approvalId?: string }) {
  const { t, tx } = useI18n()
  const { approvals, selected } = governanceSectionModel(context, approvalId)

  return (
    <>
      <div className="agent-heading">
        <h1>{t('Governance')}</h1>
        <div className="segmented">
          <button className="active">{t('Pending')}</button>
          <button>{t('Resolved')}</button>
          <button>{t('Policy')}</button>
        </div>
      </div>
      <div className="confirmation-gate-card">
        <div>
          <span className="confirmation-kicker">{t('Approval rail')}</span>
          <strong>{selected ? tx(selected.title) : t('No approval waiting')}</strong>
          <p>{selected ? tx(selected.summary) : t('High-risk tools pause here for confirmation, approval, or policy gates.')}</p>
        </div>
        <button className="composer-action-button build-submit-button" disabled={!selected}>
          {t('Review gate')}
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
  const { tx } = useI18n()
  return (
    <div className={`quality-lane-card ${approval.status}`}>
      <div>
        <span className="quality-lane-dot" />
        <strong>{tx(approval.title)}</strong>
      </div>
      <p>{tx(approval.summary)}</p>
      <span>{tx(approval.status)}</span>
    </div>
  )
}
