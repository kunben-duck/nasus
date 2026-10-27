import { useAutomationScriptReview } from '../../../../../domains/quality-loop/useAutomationScriptReview'
import type { ScriptArchive, ScriptActionDecision, ScriptOracleDecision, ScriptDecision } from '../../../../../domains/quality-loop/types/automationScripts'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeText } from './ScopeInputs'
import { RunPlanPanel } from './RunPlanPanel'

function ScriptDecisions({ draft, actions, assertions, readOnly = false, editAction, editOracle }: {
  draft: ScriptArchive; actions: ScriptActionDecision[]; assertions: ScriptOracleDecision[]; readOnly?: boolean
  editAction: (index: number, value: { decision: ScriptDecision; reason: string }) => void
  editOracle: (index: number, value: { decision: ScriptDecision; reason: string }) => void
}) {
  const { t } = useI18n()
  const decision = (value: ScriptActionDecision | ScriptOracleDecision, index: number, change: typeof editAction) => <>
    <label>{t('Review decision')}<select disabled={readOnly} value={value.decision} onChange={(event) => change(index, { decision: event.target.value as ScriptDecision, reason: value.reason })}>
      <option value="defer">{t('Defer')}</option><option value="accept">{t('Accept')}</option><option value="reject">{t('Reject')}</option></select></label>
    <ScopeText label={t('Review reason')} value={value.reason} onChange={(reason) => { if (!readOnly) change(index, { decision: value.decision, reason }) }} />
  </>
  return <fieldset className="script-decisions" disabled={readOnly}>{draft.result.proposal.scripts.map((script) => <details className="scope-record script-decision-case" key={script.case_id}>
    <summary>{draft.result.prepared.cases.find((item) => item.case_id === script.case_id)?.title} · {script.kind}</summary><code>{script.case_id}</code>
    {actions.map((value, index) => value.case_id === script.case_id && <div className="scope-record" key={`action:${index}`}>
      <strong>{t('DSL action {index}', { index: value.action_index + 1 })}</strong>
      <pre>{JSON.stringify(script.actions[value.action_index], null, 2)}</pre>{decision(value, index, editAction)}
    </div>)}
    {assertions.map((value, index) => value.case_id === script.case_id && <div className="scope-record" key={`oracle:${index}`}>
      <strong>{t('Original oracle and DSL equivalence')}</strong><code>{value.row_id}</code>
      <p>{t('Original step {step}; DSL action {action}', { step: value.source_step_index + 1, action: value.action_index + 1 })}</p>
      <p>{script.assertions.find((item) => item.row_id === value.row_id)?.oracle.expected_result}</p>
      <code>{value.oracle_digest}</code>{decision(value, index, editOracle)}
    </div>)}
  </details>)}</fieldset>
}
export function AutomationScriptReviewPanel({ draft, sessionId, onFailure }: { draft: ScriptArchive; sessionId: string; onFailure: () => void }) {
  const { t, tx } = useI18n(), state = useAutomationScriptReview(draft, sessionId, onFailure)
  const view = state.view, content = state.content
  return <section className="test-design-mapping" aria-label={t('Independent script review')}>
    <button className="small-btn" type="button" disabled={state.busy} aria-expanded={state.open} onClick={state.toggle}>{t('Inspect script review')}</button>
    {state.open && <>
      <p>{t('Review every DSL action and its equivalence to the original expected result. Acceptance is not permission to execute or proof of coverage.')}</p>
      <button className="small-btn" type="button" disabled={state.busy} onClick={state.reload}>{t('Reload script review')}</button>
      {state.busy && <p role="status">{t('Verifying script history and source access...')}</p>}
      {state.failed && <p role="alert">{t('Script history could not be verified. Protected content is hidden; reload to check current access.')}</p>}
      {state.write.isError && <p role="alert">{t('Script decision was not acknowledged. Reload the original history before another confirmation; no retry was sent.')}</p>}
      {state.write.isSuccess && <p role="status">{t('Script decision recorded; execution remains unauthorized.')}</p>}
      {view && <>
        {!view.input_current && <p>{t('The original input is stale or withdrawn. Historical scripts remain inspectable; new generation and review are blocked.')}</p>}
        {!view.head && <p>{t('No independent script review has been recorded.')}</p>}
        <label>{t('Script review history')}<select value={state.selected} disabled={state.busy} onChange={(event) => state.choose(event.target.value)}>
          <option value="">{t('Current script review head')}</option>{view.history.map((item) => <option key={item.revision_id} value={item.revision_id}>{item.sequence} · {tx(item.status)} · {item.recorded_at}</option>)}</select></label>
        {content && <div className="scope-record">
          <strong>{content.revision.status === 'withdrawn' ? t('Withdrawn script review') : t('Recorded script review; execution not authorized')}</strong>
          <code>{content.revision.revision_id}</code><small>{content.revision.authority_actor} · {content.revision.recorded_at}</small><p>{content.request.reason}</p>
          {content.assessment && <><p>{t('{actions} actions and {oracles} oracles reviewed; {accepted} accepted, {rejected} rejected, {deferred} deferred.', {
            actions: content.assessment.reviewed_action_count, oracles: content.assessment.reviewed_oracle_count,
            accepted: content.assessment.accepted_count, rejected: content.assessment.rejected_count, deferred: content.assessment.deferred_count })}</p>
            <ScriptDecisions draft={draft} actions={content.request.actions!} assertions={content.request.assertions!} readOnly editAction={() => {}} editOracle={() => {}} /></>}
        </div>}
        {view.can_review && <div className="scope-actions">
          <button className="small-btn" type="button" disabled={state.busy || !view.input_current} onClick={() => state.begin()}>{t('Review script actions and oracles')}</button>
          <button className="small-btn" type="button" disabled={state.busy || view.head?.revision.status !== 'reviewed'} onClick={() => state.begin(true)}>{t('Withdraw script review')}</button>
        </div>}
        {state.editing && view.can_review && <fieldset disabled={state.busy || !state.write.isIdle}>
          <legend>{t('New independent script decision')}</legend>
          {state.decision === 'review' && <ScriptDecisions draft={draft} actions={state.actions} assertions={state.assertions} editAction={state.editAction} editOracle={state.editOracle} />}
          <ScopeText label={t('Review reason')} value={state.reason} onChange={state.explain} />
          <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} onChange={(event) => state.confirm(event.target.checked)} />
            {state.decision === 'withdraw' ? t('I confirm withdrawal of this exact script review head.')
              : t('I independently confirm every action and original oracle decision. No target execution or test pass is authorized.')}</label>
          <button className="small-btn primary" type="button" disabled={!state.canSubmit} onClick={state.submit}>{t('Record script decision')}</button>
        </fieldset>}
        {content?.revision.status === 'reviewed' && content.assessment?.review_complete && !state.editing && <RunPlanPanel
          draft={draft} review={content} onFailure={onFailure}
          current={view.input_current && view.head?.revision.revision_id === content.revision.revision_id} />}
      </>}
    </>}
  </section>
}
