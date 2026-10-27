import type { ScopeAssessment, ScopeDimension } from '../../../../../domains/quality-loop/types/testDesignScope'
import { dimensionFields, newScopeObligation } from '../../../../../domains/quality-loop/testDesignScopeDraft'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeOracle, ScopeReferences, ScopeText } from './ScopeInputs'

export function ScopeDimensionEditor({ dimension, value, constraints, evidence, readOnly, onChange }: {
  dimension: ScopeDimension; value: ScopeAssessment; constraints: { id: string; text: string }[]; evidence: { id: string; text: string }[]
  readOnly: boolean; onChange: (value: ScopeAssessment) => void
}) {
  const { t } = useI18n()
  const names = { risks: t('Risk boundaries'), permissions: t('Permission boundaries'), transitions: t('State transitions'), invariants: t('Historical invariants') }
  const labels = { boundary: t('Risk boundary'), actor: t('Acting role'), operation: t('Operation'), resource: t('Target resource'),
    from_state: t('From state'), event: t('Triggering event'), to_state: t('To state'), invariant: t('Invariant statement'), expected: t('Permission result') }
  const editItem = (index: number, patch: Partial<ScopeAssessment['items'][number]>) =>
    onChange({ ...value, items: value.items.map((item, i) => i === index ? { ...item, ...patch } : item) })
  return <details className="scope-dimension"><summary>{names[dimension]} <span>{value.items.length}</span></summary>
    <fieldset aria-label={names[dimension]} disabled={readOnly}>
      <label>{t('Applicability')}<select value={value.applicability} onChange={(event) => onChange({ ...value,
        applicability: event.target.value as ScopeAssessment['applicability'] })}>
        <option value="">{t('Choose an assessment')}</option><option value="applicable">{t('Applicable')}</option><option value="not_applicable">{t('Not applicable')}</option>
      </select></label>
      <ScopeText label={t('Assessment rationale')} value={value.rationale} onChange={(rationale) => onChange({ ...value, rationale })} />
      {value.items.map((item, index) => <fieldset key={item.obligation_id} className="scope-item"><legend>{t('Obligation {number}', { number: index + 1 })}</legend>
        <code>{item.obligation_id}</code>
        <div className="scope-grid">{dimensionFields[dimension].map((field) => field === 'expected' ? <label key={field}>{labels[field]}
          <select value={item.expected ?? ''} onChange={(event) => editItem(index, { expected: event.target.value as 'allowed' | 'denied' | '' })}>
            <option value="">{t('Choose an assessment')}</option><option value="allowed">{t('Allowed')}</option><option value="denied">{t('Denied')}</option>
          </select></label> : <ScopeText key={field} label={labels[field]} value={item[field] ?? ''} onChange={(text) => editItem(index, { [field]: text })} />)}</div>
        <ScopeReferences title={t('Required constraints')} options={constraints} value={item.constraint_ids} onChange={(constraint_ids) => editItem(index, { constraint_ids })} />
        <details><summary>{t('Optional pinned evidence')}</summary><ScopeReferences title={t('Evidence references')} options={evidence} value={item.evidence_ids}
          onChange={(evidence_ids) => editItem(index, { evidence_ids })} /></details>
        <ScopeOracle title={t('Observable obligation')} value={item.oracle} onChange={(oracle) => editItem(index, { oracle })} />
        {!readOnly && <button type="button" className="small-btn" onClick={() => onChange({ ...value, items: value.items.filter((_, i) => i !== index) })}>{t('Remove obligation')}</button>}
      </fieldset>)}
      {!readOnly && <button type="button" className="small-btn" disabled={value.applicability !== 'applicable' || value.items.length >= 256}
        onClick={() => onChange({ ...value, items: [...value.items, newScopeObligation(dimension)] })}>{t('Add obligation')}</button>}
      {value.applicability === 'not_applicable' && value.items.length > 0 && <p role="alert">{t('Remove obligations explicitly before marking this dimension not applicable.')}</p>}
    </fieldset>
  </details>
}
