import type { ProjectRouteContext } from '../../ProjectRouteTypes'
import { MetricCard } from '../primitives/MetricCards'
import { USCard, VersionList } from './VersionCards'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function VersionSpaceSection({ context }: { context: ProjectRouteContext }) {
  const { t } = useI18n()
  const versions = context.workspace?.versions ?? []
  const activeVersion = versions[0]
  const usItems = context.workspace?.us_items ?? []

  return (
    <>
      <div className="agent-heading">
        <h1>{t('Version Space')}</h1>
        <div className="segmented">
          <button className="active">{t('Board')}</button>
          <button>{t('Risk')}</button>
          <button>{t('Activity')}</button>
        </div>
      </div>
      <div className="metric-grid">
        <MetricCard label={t('Active version')} value={activeVersion?.name ?? context.project.active_version} />
        <MetricCard label={t('US total')} value={`${activeVersion?.us_total ?? usItems.length}`} />
        <MetricCard label={t('Pending runs')} value={`${activeVersion?.pending_runs ?? context.workspace?.runs.length ?? 0}`} />
        <MetricCard label={t('Approvals')} value={`${activeVersion?.pending_approvals ?? context.project.pending_approvals}`} />
      </div>
      <div className="quality-asset-panel">
        <div className="quality-panel-header">
          <div>
            <span className="eyebrow">{t('US board')}</span>
            <strong>{context.project.name}</strong>
            <p>{t('Version-level US progress, risk, and next actions stay inside the project route module.')}</p>
          </div>
        </div>
        <div className="quality-lane-grid">
          {usItems.map((item) => (
            <USCard item={item} projectId={context.project.id} key={item.id} />
          ))}
        </div>
      </div>
      <VersionList versions={versions} />
    </>
  )
}
