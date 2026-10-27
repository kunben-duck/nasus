import type { QualityLaneCardView } from '../../projectWorkspaceSelectors'
import { useI18n } from '../../../../shared/i18n/I18nProvider'

export function QualityDraftNotice({ lanes }: { lanes: QualityLaneCardView[] }) {
  const { t } = useI18n()
  if (!lanes.some((lane) => ['draft', 'ready_for_review'].includes(lane.status))) {
    return null
  }

  return (
    <p className="quality-empty-state" role="note" data-testid="quality-draft-notice">
      {t('Generated drafts are not approved assets. Independent review and execution evidence are still required.')}
    </p>
  )
}
