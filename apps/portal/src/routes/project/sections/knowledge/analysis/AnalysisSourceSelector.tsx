import { useState } from 'react'
import { useCodeSourceRevisions, type AnalysisReadScope } from '../../../../../domains/system-image/useCodeAnalysis'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from './AnalysisPagination'
import { AnalysisReportSelector } from './AnalysisReportSelector'
import { CodeIndexInspector } from './CodeIndexInspector'

export function AnalysisSourceSelector({ scope }: { scope: AnalysisReadScope }) {
  const { t } = useI18n()
  const [cursors, setCursors] = useState([''])
  const [chosen, setChosen] = useState('')
  const query = useCodeSourceRevisions(scope, cursors.at(-1)!)
  const source = query.data?.items.find((item) => item.source_revision_id === chosen)
  if (!query.isFetching && chosen && !source) setChosen('')
  if (query.isError) return null
  if (query.isPending) return <p role="status">{t('Checking source access...')}</p>
  const move = (next: string[]) => { setChosen(''); setCursors(next) }
  return <>
    {query.isFetching && <p role="status">{t('Checking source access...')}</p>}
    <div hidden={query.isFetching}>
    <label className="evidence-selector">{t('Captured code revision')}
      <select value={chosen} onChange={(event) => setChosen(event.target.value)}>
        <option value="">{t('Choose a source revision')}</option>
        {query.data.items.map((item) => <option key={item.source_revision_id} value={item.source_revision_id}>
          {item.source_label} · {item.external_revision.slice(0, 14)} · {item.acquired_at.slice(0, 19).replace('T', ' ')}
        </option>)}
      </select>
    </label>
    {!query.data.items.length && <p>{t('No captured code revisions are available to you. Capture a code source before inspecting it.')}</p>}
    <AnalysisPagination page={cursors.length} previous={cursors.length > 1 ? () => move(cursors.slice(0, -1)) : undefined}
      next={query.data.next_after_id ? () => move([...cursors, query.data.next_after_id!]) : undefined} />
    {source && <section className="analysis-source" key={source.source_revision_id}>
      <AnalysisReportSelector scope={scope} revisionId={source.source_revision_id} />
      <CodeIndexInspector scope={scope} bindingId={source.binding_id} />
    </section>}
    </div>
  </>
}
