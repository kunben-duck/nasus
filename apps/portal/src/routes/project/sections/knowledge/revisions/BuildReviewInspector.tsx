import { useId } from 'react'
import { useBuildReviewHandoff } from '../../../../../domains/system-image/useBuildReviewHandoff'
import type { BuildReviewSelection } from '../../../../../domains/system-image/buildReviewHandoff'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ImageRevisionInspector } from './ImageRevisionInspector'

export function BuildReviewInspector({ projectId, selection, close }: {
  projectId: string; selection: BuildReviewSelection; close: () => void
}) {
  const { t } = useI18n(), sessionId = useId()
  const query = useBuildReviewHandoff(projectId, selection, sessionId)
  if (query.isFetching) return <p role="status">{t('Verifying the original build findings and source access...')}</p>
  if (query.isError || !query.data) return <div role="alert" data-testid="build-review-handoff-unverified">
    <p>{t('The original build review could not be verified. No other candidate was selected and no publication was sent.')}</p>
    <button type="button" onClick={() => { void query.refetch() }}>{t('Reload build findings')}</button>
    <button type="button" onClick={close}>{t('Close')}</button>
  </div>
  return <ImageRevisionInspector projectId={projectId} baselines={[query.data.targetBaseline]} close={close} review={query.data}
    reloadReview={() => { void query.refetch() }} />
}
