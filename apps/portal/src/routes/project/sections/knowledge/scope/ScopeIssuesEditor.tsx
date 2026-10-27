import type { ScopeConflict, ScopeGap } from '../../../../../domains/quality-loop/types/testDesignScope'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeReferences, ScopeText } from './ScopeInputs'

export function ScopeIssuesEditor({ gaps, conflicts, constraints, readOnly, onGaps, onConflicts }: {
  gaps: ScopeGap[]; conflicts: ScopeConflict[]; constraints: { id: string; text: string }[]; readOnly: boolean
  onGaps: (values: ScopeGap[]) => void; onConflicts: (values: ScopeConflict[]) => void
}) {
  const { t } = useI18n()
  return <details className="scope-issues"><summary>{t('Explicit gaps and conflicts')} <span>{gaps.length + conflicts.length}</span></summary>
    <p>{t('Gaps and unresolved conflicts block completeness. Removing a linked gap requires reassessing its negative examples.')}</p>
    {gaps.map((item, index) => <fieldset key={item.id} className="scope-item"><legend>{t('Gap {number}', { number: index + 1 })}</legend>
      <code>{item.id}</code><ScopeText label={t('Gap description')} value={item.description}
        onChange={(description) => onGaps(gaps.map((entry, i) => i === index ? { ...entry, description } : entry))} />
      <ScopeReferences title={t('Required constraints')} options={constraints} value={item.constraint_ids}
        onChange={(constraint_ids) => onGaps(gaps.map((entry, i) => i === index ? { ...entry, constraint_ids } : entry))} />
      {!readOnly && <button className="small-btn" type="button" onClick={() => onGaps(gaps.filter((_, i) => i !== index))}>{t('Remove gap')}</button>}
    </fieldset>)}
    {!readOnly && <button className="small-btn" type="button" disabled={gaps.length >= 256} onClick={() => onGaps([...gaps, { id: crypto.randomUUID(), description: '', constraint_ids: [] }])}>{t('Add gap')}</button>}
    {conflicts.map((item, index) => <fieldset key={item.id} className="scope-item"><legend>{t('Conflict {number}', { number: index + 1 })}</legend>
      <code>{item.id}</code><ScopeText label={t('Conflict description')} value={item.description}
        onChange={(description) => onConflicts(conflicts.map((entry, i) => i === index ? { ...entry, description } : entry))} />
      <ScopeReferences title={t('Required constraints')} options={constraints} value={item.constraint_ids}
        onChange={(constraint_ids) => onConflicts(conflicts.map((entry, i) => i === index ? { ...entry, constraint_ids } : entry))} />
      <ScopeText label={t('Conflict resolution (leave blank if unresolved)')} value={item.resolution ?? ''}
        onChange={(resolution) => onConflicts(conflicts.map((entry, i) => i === index ? { ...entry, resolution: resolution || null } : entry))} />
      {!readOnly && <button className="small-btn" type="button" onClick={() => onConflicts(conflicts.filter((_, i) => i !== index))}>{t('Remove conflict')}</button>}
    </fieldset>)}
    {!readOnly && <button className="small-btn" type="button" disabled={conflicts.length >= 256}
      onClick={() => onConflicts([...conflicts, { id: crypto.randomUUID(), description: '', constraint_ids: [], resolution: null }])}>{t('Add conflict')}</button>}
  </details>
}
