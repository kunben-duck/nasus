import { useState } from 'react'
import { useImageRevisions, type ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from '../analysis/AnalysisPagination'
import { ImageRevisionData } from './ImageRevisionData'
import type { ImageBaselineOption } from '../../../../../domains/system-image/types/baseline'

export function ImageRevisionSelector({ scope, baselines }: { scope: ImageReadScope; baselines: ImageBaselineOption[] }) {
  const { t } = useI18n()
  const [cursors, setCursors] = useState([''])
  const [chosen, setChosen] = useState('')
  const query = useImageRevisions(scope, cursors.at(-1)!)
  const revision = query.data?.items.find((item) => item.image_revision_id === chosen)
  if (!query.isFetching && chosen && !revision) setChosen('')
  if (query.isError) return null
  if (query.isPending) return <p role="status">{t('Checking source access...')}</p>
  const move = (next: string[]) => { setChosen(''); setCursors(next) }
  return <>
    {query.isFetching && <p role="status">{t('Checking source access...')}</p>}
    {/* Revalidate access without cancelling in-flight reads or losing pagination. */}
    <div hidden={query.isFetching}>
    <label className="evidence-selector">{t('Frozen candidate revision')}
      <select value={chosen} onChange={(event) => setChosen(event.target.value)}>
        <option value="">{t('Choose an image revision')}</option>
        {query.data.items.map((item) => <option key={item.image_revision_id} value={item.image_revision_id}>
          {item.recorded_at.slice(0, 19).replace('T', ' ')} · {item.image_revision_id.slice(0, 8)} · {t('{count} objects', { count: item.object_count })}
        </option>)}
      </select>
    </label>
    {!query.data.items.length && <p>{t('No frozen candidates are available to you. Materialize captured sources to create one.')}</p>}
    <AnalysisPagination label={t('Revision list pages')} page={cursors.length} previous={cursors.length > 1 ? () => move(cursors.slice(0, -1)) : undefined}
      next={query.data.next_after_id ? () => move([...cursors, query.data.next_after_id!]) : undefined} />
    {revision && <ImageRevisionData key={revision.image_revision_id} scope={scope} revisionId={revision.image_revision_id} baselines={baselines} />}
    </div>
  </>
}
