import type { ScopeExample, ScopeGap } from '../../../../../domains/quality-loop/types/testDesignScope'
import { blankOracle } from '../../../../../domains/quality-loop/testDesignScopeDraft'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeOracle, ScopeText } from './ScopeInputs'

export function ScopeExamplesEditor({ values, constraints, gaps, onChange }: {
  values: ScopeExample[]; constraints: { id: string; text: string }[]; gaps: ScopeGap[]; onChange: (values: ScopeExample[]) => void
}) {
  const { t } = useI18n()
  const edit = (index: number, patch: Partial<ScopeExample>) => onChange(values.map((item, i) => i === index ? { ...item, ...patch } : item))
  return <details className="scope-examples"><summary>{t('Positive and negative examples')} <span>{values.length}</span></summary>
    <p>{t('Every AC and business rule remains in scope. Positive examples start from the approved oracle and require your review.')}</p>
    {values.map((item, index) => <details key={item.constraint_id} className="scope-example">
      <summary>{constraints.find((constraint) => constraint.id === item.constraint_id)?.text ?? item.constraint_id}</summary>
      <code>{item.constraint_id}</code><ScopeOracle title={t('Positive example')} value={item.positive} onChange={(positive) => edit(index, { positive })} />
      <label>{t('Negative example assessment')}<select value={item.negative !== null ? 'oracle' : item.negative_not_applicable_reason !== null ? 'not_applicable' : item.negative_gap_id !== null ? 'gap' : ''}
        onChange={(event) => edit(index, { negative: event.target.value === 'oracle' ? blankOracle() : null,
          negative_not_applicable_reason: event.target.value === 'not_applicable' ? '' : null, negative_gap_id: event.target.value === 'gap' ? '' : null })}>
        <option value="">{t('Choose an assessment')}</option><option value="oracle">{t('Observable negative example')}</option>
        <option value="not_applicable">{t('Not applicable with reason')}</option><option value="gap">{t('Unknown; link a blocking gap')}</option>
      </select></label>
      {item.negative && <ScopeOracle title={t('Negative example')} value={item.negative} onChange={(negative) => edit(index, { negative })} />}
      {item.negative_not_applicable_reason !== null && <ScopeText label={t('Negative example not-applicable reason')} value={item.negative_not_applicable_reason}
        onChange={(negative_not_applicable_reason) => edit(index, { negative_not_applicable_reason })} />}
      {item.negative_gap_id !== null && <label>{t('Blocking gap')}<select value={item.negative_gap_id} onChange={(event) => edit(index, { negative_gap_id: event.target.value })}>
        <option value="">{t('Choose a gap covering this constraint')}</option>{gaps.filter((gap) => gap.constraint_ids.includes(item.constraint_id)).map((gap) =>
          <option key={gap.id} value={gap.id}>{gap.description || gap.id}</option>)}</select></label>}
    </details>)}
  </details>
}
