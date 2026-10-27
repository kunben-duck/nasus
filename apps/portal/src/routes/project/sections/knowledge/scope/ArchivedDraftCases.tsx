import type { ReactNode } from 'react'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function ArchivedDraftCases({ draft, children }: { draft: GenerationArchive; children: ReactNode }) {
  const { t } = useI18n(), proposal = draft.result.proposal
  return <div className="scope-record" aria-label={t('Archived draft test cases')}>
    <strong>{t('{cases} draft cases; {planned}/{total} obligations planned', { cases: draft.metadata.case_count,
      planned: proposal.coverage.planned_obligation_count, total: proposal.coverage.obligation_denominator })}</strong>
    <p>{t('Independent mapping, automated, executed and passed counts are all zero. These drafts do not authorize target execution.')}</p>
    <p>{t('Original draft counts are immutable. Independent mapping reviews are shown separately below.')}</p>
    {!draft.current_use.scope_current && <p>{t('Historical draft; its original scope no longer authorizes current generation.')}</p>}
    <code>{draft.metadata.generation_id}</code>
    {proposal.cases.map((item) => <details key={item.case_id}><summary>{item.title}</summary>
      <code>{item.case_id}</code><strong>{t('Preconditions')}</strong><ul>{item.preconditions.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <strong>{t('Test inputs')}</strong><ul>{item.inputs.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <strong>{t('Test steps')}</strong><ol>{item.steps.map((text, index) => <li key={index}>{text}</li>)}</ol>
      {item.assertions.map((a) => <div key={a.row_id}><code>{a.row_id}</code><p>{a.oracle.expected_result}</p></div>)}</details>)}
    {proposal.gaps.map((gap) => <p key={gap.gap_id}><strong>{t('Generation gap')}</strong> {gap.description}</p>)}
    {children}
  </div>
}
