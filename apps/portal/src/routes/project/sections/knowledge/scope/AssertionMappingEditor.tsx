import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import type { AssertionReview } from '../../../../../domains/quality-loop/types/testDesignMapping'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeText } from './ScopeInputs'

export function AssertionMappingEditor({ draft, values, readOnly = false, onChange }: {
  draft: GenerationArchive; values: AssertionReview[]; readOnly?: boolean
  onChange: (index: number, value: Pick<AssertionReview, 'decision' | 'reason'>) => void
}) {
  const { t } = useI18n()
  const labels = { accept: t('Accept'), reject: t('Reject'), defer: t('Defer') }
  const cases = new Map(draft.result.proposal.cases.map((item) => [item.case_id, item]))
  return <div className="mapping-assertions">{values.map((value, index) => {
    const item = cases.get(value.case_id)!, assertion = item.assertions.find((a) => a.row_id === value.row_id)!
    return <fieldset key={JSON.stringify([value.case_id, value.row_id])} aria-label={t('Assertion mapping {index}', { index: index + 1 })}>
      <legend>{item.title}</legend><code>{value.case_id}</code><code>{value.row_id}</code>
      <p><strong>{t('Fixed test step')}</strong> {value.step_index + 1} · {item.steps[value.step_index]}</p>
      <dl><dt>{t('Oracle preconditions')}</dt><dd>{assertion.oracle.preconditions}</dd>
        <dt>{t('Action under test')}</dt><dd>{assertion.oracle.action}</dd>
        <dt>{t('Observable output')}</dt><dd>{assertion.oracle.observation}</dd>
        <dt>{t('Required result')}</dt><dd>{assertion.oracle.expected_result}</dd></dl>
      {readOnly ? <><strong>{labels[value.decision]}</strong><p>{value.reason}</p></> : <>
        <label>{t('Mapping decision')}<select value={value.decision} onChange={(event) => onChange(index, { ...value, decision: event.target.value as AssertionReview['decision'] })}>
          {(['defer', 'accept', 'reject'] as const).map((decision) => <option key={decision} value={decision}>{labels[decision]}</option>)}</select></label>
        <ScopeText label={t('Assertion review reason')} value={value.reason} onChange={(reason) => onChange(index, { ...value, reason })} />
      </>}
    </fieldset>
  })}</div>
}
