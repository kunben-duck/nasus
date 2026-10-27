import { useState } from 'react'
import { useCodeAnalysisList, type AnalysisReadScope } from '../../../../../domains/system-image/useCodeAnalysis'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from './AnalysisPagination'
import { AnalysisReportData } from './AnalysisReportData'

export function AnalysisReportSelector({ scope, revisionId }: { scope: AnalysisReadScope; revisionId: string }) {
  const { t } = useI18n()
  const [cursors, setCursors] = useState([''])
  const [chosen, setChosen] = useState('')
  const query = useCodeAnalysisList(scope, revisionId, cursors.at(-1)!)
  const report = query.data?.items.find((item) => item.analysis_id === chosen)
  if (!query.isFetching && chosen && !report) setChosen('')
  if (query.isError) return null
  if (query.isPending) return <p role="status">{t('Loading analysis reports...')}</p>
  const move = (next: string[]) => { setChosen(''); setCursors(next) }
  return <>
    {query.isFetching && <p role="status">{t('Loading analysis reports...')}</p>}
    <div hidden={query.isFetching}>
    <label className="evidence-selector">{t('Analysis report')}
      <select value={chosen} onChange={(event) => setChosen(event.target.value)}>
        <option value="">{t('Choose a report')}</option>
        {query.data.items.map((item) => <option key={item.analysis_id} value={item.analysis_id}>
          {item.provider} {item.provider_version} · {item.recorded_at.slice(0, 19).replace('T', ' ')} · {item.analysis_id.slice(0, 8)}
        </option>)}
      </select>
    </label>
    {!query.data.items.length && <p>{t('No analysis report exists for this revision. Materialize its context to create parser diagnostics.')}</p>}
    <AnalysisPagination page={cursors.length} previous={cursors.length > 1 ? () => move(cursors.slice(0, -1)) : undefined}
      next={query.data.next_after_id ? () => move([...cursors, query.data.next_after_id!]) : undefined} />
    {report && <AnalysisReportData key={report.analysis_id} scope={scope} revisionId={revisionId} analysisId={report.analysis_id} />}
    </div>
  </>
}
