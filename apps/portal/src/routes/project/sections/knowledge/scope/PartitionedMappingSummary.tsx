import { useState } from 'react'
import type { PartitionedMappingArchive } from '../../../../../domains/quality-loop/types/testDesignMapping'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function PartitionedMappingSummary({ content }: { content: PartitionedMappingArchive }) {
  const { t } = useI18n(), [page, setPage] = useState(0)
  const rows = content.assessment.coverage.rows, size = 20
  const start = page * size, selected = rows.slice(start, start + size)
  return <div className="partitioned-mapping-summary" aria-label={t('Verified partitioned mapping')}>
    <p>{t('{parts} immutable parts bind all {assertions} assertion pairs. Private staging reasons are not exposed.', {
      parts: content.part_set.part_count, assertions: content.part_set.assertion_count })}</p>
    <code>{content.part_set.part_set_digest}</code>
    <ul>{selected.map((row) => <li key={row.row_id}><code>{row.row_id}</code>
      <p>{t('Accepted: {accepted}; rejected: {rejected}; deferred: {deferred}.', {
        accepted: row.accepted_case_ids.length, rejected: row.rejected_case_ids.length, deferred: row.deferred_case_ids.length })}</p>
      {(['accepted_case_ids', 'rejected_case_ids', 'deferred_case_ids'] as const).map((field) => <details key={field}>
        <summary>{t(field === 'accepted_case_ids' ? 'Accepted cases' : field === 'rejected_case_ids' ? 'Rejected cases' : 'Deferred cases')}</summary>
        <p>{row[field].join(', ') || t('None')}</p>
      </details>)}
    </li>)}</ul>
    <p>{t('Showing {start}–{end} of {total} obligations.', { start: Math.min(start + 1, rows.length), end: Math.min(start + size, rows.length), total: rows.length })}</p>
    <div className="scope-actions"><button type="button" className="small-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>{t('Previous obligations')}</button>
      <button type="button" className="small-btn" disabled={start + size >= rows.length} onClick={() => setPage(page + 1)}>{t('Next obligations')}</button></div>
  </div>
}
