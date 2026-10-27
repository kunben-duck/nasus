import type { ImageRevisionSummary } from '../../../../../domains/system-image/types/imageRevision'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function ImageRevisionProvenance({ revision }: { revision: ImageRevisionSummary }) {
  const { t, tx } = useI18n()
  const entries = [
    ['Revision ID', revision.image_revision_id], ['Recorded at', revision.recorded_at],
    ['Source manifest', revision.manifest_id], ['Manifest hash', revision.manifest_hash],
    ['Artifact hash', revision.artifact_hash], ['Membership hash', revision.membership_hash],
    ['Analysis rule set', revision.policy_version],
    ...(revision.parent_revision_id ? [['Parent revision', revision.parent_revision_id], ['Parent artifact hash', revision.parent_artifact_hash ?? '']] : []),
  ]
  return <details className="evidence-integrity-details"><summary>{t('Revision provenance')}</summary>
    <dl>{entries.map(([label, value]) => <div key={label}><dt>{tx(label)}</dt><dd>{value}</dd></div>)}</dl>
  </details>
}
