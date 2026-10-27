import { useState } from 'react'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import type { AssertionReview } from '../../../../../domains/quality-loop/types/testDesignMapping'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { AssertionMappingEditor } from './AssertionMappingEditor'

export function MappingPartAssertions({ draft, values, readOnly = false, onChange }: {
  draft: GenerationArchive; values: AssertionReview[]; readOnly?: boolean
  onChange: (index: number, value: Pick<AssertionReview, 'decision' | 'reason'>) => void
}) {
  const { t } = useI18n(), [page, setPage] = useState(0), size = 8, start = page * size
  return <div className="mapping-part-assertions">
    <p>{t('Showing {start}–{end} of {total} assertion pairs in this part.', {
      start: start + 1, end: Math.min(start + size, values.length), total: values.length })}</p>
    <div className="mapping-part-scroll"><AssertionMappingEditor draft={draft} values={values.slice(start, start + size)}
      readOnly={readOnly} onChange={(index, value) => onChange(start + index, value)} /></div>
    <div className="scope-actions"><button type="button" className="small-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>{t('Previous assertions')}</button>
      <button type="button" className="small-btn" disabled={start + size >= values.length} onClick={() => setPage(page + 1)}>{t('Next assertions')}</button></div>
  </div>
}
