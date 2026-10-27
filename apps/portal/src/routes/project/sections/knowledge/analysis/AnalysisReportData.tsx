import { useState } from 'react'
import { useCodeAnalysisPage, type AnalysisReadScope } from '../../../../../domains/system-image/useCodeAnalysis'
import { analysisSectionLabels, identityLabels, parserLabels, relationLabels, structureLabels } from '../../../../../domains/system-image/codeAnalysisLabels'
import type { AnalysisPageSelection } from '../../../../../domains/system-image/types/codeAnalysis'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AnalysisPagination } from './AnalysisPagination'
import { AnalysisObservationList } from './AnalysisObservationList'
import { analysisObservationViews } from './analysisObservationView'
import { CodeProjectionDetails } from './CodeProjectionDetails'

export function AnalysisReportData({ scope, revisionId, analysisId }: { scope: AnalysisReadScope; revisionId: string; analysisId: string }) {
  const { t, tx } = useI18n()
  const [selection, setSelection] = useState<AnalysisPageSelection>({ section: 'files', filter: '', offset: 0 })
  const query = useCodeAnalysisPage(scope, revisionId, analysisId, selection)
  const labels = { files: parserLabels, facts: structureLabels, entities: identityLabels, relationships: relationLabels }[selection.section]
  const hasArchive = Boolean(query.data?.analysis.observation_summary) || ['entities', 'relationships'].includes(selection.section)
  const sections = hasArchive ? ['files', 'facts', 'entities', 'relationships'] as const : ['files', 'facts'] as const
  return <section className="analysis-report">
    <div className="analysis-report-controls">
      <div className="segmented" role="group" aria-label={t('Report section')}>
        {sections.map((section) => <button type="button" key={section} aria-pressed={selection.section === section}
          className={selection.section === section ? 'active' : ''} onClick={() => setSelection({ section, filter: '', offset: 0 })}>
          {tx(analysisSectionLabels[section])}</button>)}
      </div>
      <label className="evidence-selector">{tx({ files: 'Parser status', facts: 'Structure kind', entities: 'Identity status', relationships: 'Relation kind' }[selection.section])}
        <select value={selection.filter} onChange={(event) => setSelection({ ...selection, offset: 0, filter: event.target.value })}>
          <option value="">{t('All observations')}</option>
          {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{tx(label)}</option>)}
        </select>
      </label>
    </div>
    {query.isError ? null : query.isPending || query.isFetching ? <p role="status">{t('Loading analysis observations...')}</p> : <>
      <dl className="analysis-counts" aria-label={t('Parser coverage')}>
        {Object.entries({ file_count: 'Archived files', ...parserLabels }).map(([key, label]) => <div key={key}>
          <dt>{tx(label)}</dt><dd>{query.data.analysis.summary[key as keyof typeof query.data.analysis.summary]}</dd>
        </div>)}
      </dl>
      {!query.data.analysis.raw_inventory_available && <p>{t('Legacy snapshot: the raw acquisition inventory is unavailable.')}</p>}
      <CodeProjectionDetails projection={query.data.analysis.projection} />
      {query.data.analysis.observation_summary && <p>{t('Archived received projection: {entities} entities, {relations} relations. This is not a claim of complete native graph coverage.', {
        entities: query.data.analysis.observation_summary.entity_count, relations: query.data.analysis.observation_summary.relationship_count,
      })}</p>}
      <p>{t('{count} matching observations', { count: query.data.total })}</p>
      {!query.data.items.length ? <p>{t('No matching observations. This does not prove that the capability is absent.')}</p>
        : <AnalysisObservationList items={analysisObservationViews(query.data.items)} />}
      <AnalysisPagination page={Math.floor(selection.offset / 25) + 1}
        previous={selection.offset > 0 ? () => setSelection({ ...selection, offset: Math.max(0, selection.offset - 25) }) : undefined}
        next={query.data.next_offset !== null ? () => setSelection({ ...selection, offset: query.data.next_offset! }) : undefined} />
      <details className="evidence-integrity-details"><summary>{t('Report provenance')}</summary><dl>
        <dt>{t('Pinned source revision')}</dt><dd>{revisionId}</dd>
        <dt>{t('Report ID')}</dt><dd>{analysisId}</dd><dt>{t('Report hash')}</dt><dd>{query.data.analysis.report_hash}</dd>
        <dt>{t('Analysis rule set')}</dt><dd>{query.data.analysis.algorithm}</dd>
      </dl></details>
    </>}
  </section>
}
