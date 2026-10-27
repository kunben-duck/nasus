import { useId } from 'react'
import { useWorkingImage } from '../../../../domains/system-image/useWorkingImage'
import { useI18n } from '../../../../shared/i18n/I18nProvider'
import { ImageRevisionInspector } from './revisions/ImageRevisionInspector'
import { BuildPlanInspector } from './plans/BuildPlanInspector'

export function WorkingImageInspector({ projectId, kind, close }: {
  projectId: string; kind: 'revisions' | 'plans'; close: () => void
}) {
  const sessionId = useId(), { t } = useI18n()
  const query = useWorkingImage(projectId, sessionId)
  if (query.isError) return <div role="alert"><p>{t('Working draft could not be verified. Reload to check access.')}</p>
    <button type="button" onClick={() => { void query.refetch() }}>{t('Reload working draft')}</button>
    <button type="button" onClick={close}>{t('Close')}</button></div>
  if (!query.data) return <p role="status">{t('Loading working draft...')}</p>
  return <div hidden={query.isFetching}>
    {kind === 'revisions'
      ? <ImageRevisionInspector projectId={projectId} close={close} baselines={query.data.baselines} />
      : <BuildPlanInspector projectId={projectId} close={close} baselines={query.data.baselines}
        manifestId={query.data.source_manifest?.manifest_id} />}
  </div>
}
