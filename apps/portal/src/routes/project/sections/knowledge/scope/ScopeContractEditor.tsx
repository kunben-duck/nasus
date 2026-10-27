import type { TestDesignContext } from '../../../../../domains/system-image/types/contextPack'
import type { TestDesignContract } from '../../../../../domains/quality-loop/types/testDesignScope'
import { scopeDimensions } from '../../../../../domains/quality-loop/testDesignScopeDraft'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeDimensionEditor } from './ScopeDimensionEditor'
import { ScopeExamplesEditor } from './ScopeExamplesEditor'
import { ScopeIssuesEditor } from './ScopeIssuesEditor'
import { ScopeReferences, ScopeText } from './ScopeInputs'

export function ScopeContractEditor({ context, value, readOnly = false, onChange }: {
  context: TestDesignContext; value: TestDesignContract; readOnly?: boolean; onChange: (value: TestDesignContract) => void
}) {
  const { t } = useI18n()
  const constraints = context.required_constraints.map((item) => ({ id: item.object_id, text: item.source_fields.map((field) => field.value).join('\n') }))
  const evidence = [...new Set([...context.required_constraints.flatMap((item) => item.evidence_ids), ...context.facts.flatMap((item) => item.endpoint.evidence_ids)])]
    .map((id) => ({ id, text: '' }))
  const cases = [...new Map(context.facts.filter((item) => item.relation === 'asserts').map((item) => [item.endpoint.object_id,
    { id: item.endpoint.object_id, text: item.endpoint.title }])).values()]
  return <fieldset className="scope-contract" disabled={readOnly}>
    <legend>{readOnly ? t('Recorded scope contract') : t('Scope contract')}</legend>
    {scopeDimensions.map((dimension) => <ScopeDimensionEditor key={dimension} dimension={dimension} value={value[dimension]}
      constraints={constraints} evidence={evidence} readOnly={readOnly} onChange={(assessment) => onChange({ ...value, [dimension]: assessment })} />)}
    <ScopeIssuesEditor constraints={constraints} gaps={value.gaps} conflicts={value.conflicts} readOnly={readOnly}
      onGaps={(gaps) => onChange({ ...value, gaps })} onConflicts={(conflicts) => onChange({ ...value, conflicts })} />
    <ScopeExamplesEditor constraints={constraints} values={value.examples} gaps={value.gaps} onChange={(examples) => onChange({ ...value, examples })} />
    <details><summary>{t('Test reuse and conflict assessment')}</summary>
      {cases.length > 0 ? <ScopeReferences title={t('Reusable test candidates')} options={cases} value={value.reused_case_ids}
        onChange={(reused_case_ids) => onChange({ ...value, reused_case_ids })} /> : <p>{t('No pinned reusable test candidates.')}</p>}
      <ScopeText label={t('Reuse assessment')} value={value.reuse_assessment} onChange={(reuse_assessment) => onChange({ ...value, reuse_assessment })} />
      <ScopeText label={t('Conflict assessment')} value={value.conflict_assessment} onChange={(conflict_assessment) => onChange({ ...value, conflict_assessment })} />
    </details>
  </fieldset>
}
