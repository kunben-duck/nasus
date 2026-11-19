import { useState, type ReactNode } from 'react'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { CaseRevisionEditor } from './CaseRevisionEditor'
import { TestDesignMappingPanel } from './TestDesignMappingPanel'
import { useAuthUser } from '../../../../../domains/platform/useAuthSession'

export function ArchivedDraftCases(props: { draft: GenerationArchive; children: ReactNode }) {
  const actor = useAuthUser()
  if (!actor.data || actor.isError) return null
  return <RevisionCases key={`${actor.data.id}:${props.draft.metadata.artifact_hash}`} {...props} />
}

function RevisionCases({ draft: original, children }: { draft: GenerationArchive; children: ReactNode }) {
  const [edited, setEdited] = useState<GenerationArchive | null>(null), [failed, setFailed] = useState(false)
  const { t } = useI18n(), actor = useAuthUser(), draft = edited ?? original, proposal = draft.result.proposal
  if (failed) return <p role="alert">{t('Draft review access or integrity could not be verified. The list, draft and mapping are hidden; reload to check reviewer and source access.')}</p>
  return <div className="scope-record" aria-label={t('Archived draft test cases')}>
    <strong>{t('{cases} draft cases; {planned}/{total} obligations planned', { cases: draft.metadata.case_count,
      planned: proposal.coverage.planned_obligation_count, total: proposal.coverage.obligation_denominator })}</strong>
    <p>{t('Independent mapping, automated, executed and passed counts are all zero. These drafts do not authorize target execution.')}</p>
    <p>{t('Original draft counts are immutable. Independent mapping reviews are shown separately below.')}</p>
    {!draft.current_use.scope_current && <p>{t('Historical draft; its original scope no longer authorizes current generation.')}</p>}
    <code>{draft.metadata.generation_id}</code>
    {draft.result.schema === 'nasus.test-design-case-revision.v1' && <p>{t('Human-edited revision; original model output is preserved.')} <code>{draft.result.original_generation_id}</code></p>}
    {proposal.cases.map((item) => <details key={item.case_id}><summary>{item.title}</summary>
      <code>{item.case_id}</code><strong>{t('Preconditions')}</strong><ul>{item.preconditions.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <strong>{t('Test inputs')}</strong><ul>{item.inputs.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <strong>{t('Test steps')}</strong><ol>{item.steps.map((text, index) => <li key={index}>{text}</li>)}</ol>
      {item.assertions.map((a) => <div key={a.row_id}><code>{a.row_id}</code><p>{a.oracle.expected_result}</p></div>)}</details>)}
    {proposal.gaps.map((gap) => <p key={gap.gap_id}><strong>{t('Generation gap')}</strong> {gap.description}</p>)}
    <CaseRevisionEditor key={draft.metadata.generation_id} draft={draft} onSaved={setEdited} />
    {edited && actor.data ? <TestDesignMappingPanel key={draft.metadata.generation_id} draft={draft} sessionId={actor.data.id} onFailure={() => setFailed(true)} /> : children}
  </div>
}
