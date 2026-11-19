import { useRef, useState } from 'react'
import { useAuthUser } from '../../../../../domains/platform/useAuthSession'
import { reviseCases } from '../../../../../domains/quality-loop/caseRevisions'
import { caseRevisionRequest } from '../../../../../domains/quality-loop/caseRevisionValidation'
import type { GenerationArchive, PlannedCase } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function CaseRevisionEditor({ draft, onSaved }: { draft: GenerationArchive; onSaved: (value: GenerationArchive) => void }) {
  const { t } = useI18n(), actor = useAuthUser(), processing = useRef(false)
  const [editing, setEditing] = useState<PlannedCase | null>(null), [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(false)
  let valid = false
  if (editing) {
    try { caseRevisionRequest(draft, [editing], reason); valid = true }
    catch { /* Incomplete or unchanged forms do not create commands. */ }
  }
  function change(value: PlannedCase) { setEditing(value); setConfirmed(false) }
  async function save() {
    if (processing.current || !editing || !actor.data || !confirmed || !valid) return
    processing.current = true; setBusy(true); setError(false)
    try { onSaved(await reviseCases(actor.data.id, draft, [editing], reason)); setEditing(null); setReason('') }
    catch { setError(true) }
    finally { processing.current = false; setBusy(false); setConfirmed(false) }
  }
  if (!draft.current_use.scope_current || !actor.data || actor.isError) return null
  return <section className="scope-record" aria-label={t('Edit test case revision')}>
    <label>{t('Edit test case revision')}<select value={editing?.case_id ?? ''} disabled={busy} onChange={(event) => {
      setEditing(structuredClone(draft.result.proposal.cases.find((item) => item.case_id === event.target.value) ?? null)); setConfirmed(false)
    }}><option value="">{t('Select a test case')}</option>{draft.result.proposal.cases.map((item) => <option key={item.case_id} value={item.case_id}>{item.title}</option>)}</select></label>
    {editing && <fieldset disabled={busy}>
      <p>{t('Edits create a new revision. Business expectations stay locked; mappings, case approval and scripts must be reviewed again.')}</p>
      <label>{t('Title')}<input value={editing.title} maxLength={2000} onChange={(event) => change({ ...editing, title: event.target.value })} /></label>
      {(['preconditions', 'inputs', 'steps'] as const).map((field) => <label key={field}>{t(({ preconditions: 'Preconditions', inputs: 'Test inputs', steps: 'Test steps' } as const)[field])}
        <textarea rows={4} value={editing[field].join('\n')} onChange={(event) => change({ ...editing, [field]: event.target.value.split('\n') })} /></label>)}
      <p>{t('One item per line. Assertion step numbers start at 1.')}</p>
      {editing.assertions.map((assertion, index) => <label key={assertion.row_id}>{assertion.oracle.expected_result}
        <input type="number" min={1} max={editing.steps.length} value={assertion.step_index + 1} onChange={(event) => change({ ...editing,
          assertions: editing.assertions.map((item, i) => i === index ? { ...item, step_index: Number(event.target.value) - 1 } : item) })} /></label>)}
      <label>{t('Reason')}<textarea value={reason} maxLength={2000} onChange={(event) => { setReason(event.target.value); setConfirmed(false) }} /></label>
      <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />{t('I confirm this case revision and the need for independent review.')}</label>
      <button type="button" className="small-btn primary" disabled={!confirmed || !valid} onClick={() => void save()}>{t('Save case revision')}</button>
    </fieldset>}
    {error && <p role="alert">{t('Case revision could not be verified. Inspect the original command before retrying.')}</p>}
  </section>
}
