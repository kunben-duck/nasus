import { useState } from 'react'
import { imageRecordOffset } from '../../../../../domains/system-image/imageRecordPosition'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function ImageRecordNavigation({ offset, count, total, move }: {
  offset: number; count: number; total: number; move: (offset: number) => void
}) {
  const { t } = useI18n()
  const [position, setPosition] = useState(String(offset + 1))
  const next = imageRecordOffset(position, total)
  if (total < 2) return null
  return <form className="image-record-navigation" aria-label={t('Record navigation')}
    onSubmit={(event) => { event.preventDefault(); if (next !== null && next !== offset) move(next) }}>
    <span>{t('Records {start} to {end} of {total}', { start: offset + 1, end: offset + count, total })}</span>
    <label>{t('Start at record')}
      <input type="number" min={1} max={total} step={1} required value={position}
        onChange={(event) => setPosition(event.target.value)} />
    </label>
    <button type="submit" disabled={next === null || next === offset}>{t('Go to record')}</button>
  </form>
}
