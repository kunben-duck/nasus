import { useAutomationScripts } from '../../../../../domains/quality-loop/useAutomationScripts'
import type { GenerationArchive } from '../../../../../domains/quality-loop/types/testDesignGeneration'
import type { RecordedMappingArchive } from '../../../../../domains/quality-loop/types/testDesignMapping'
import type { BudgetField } from '../../../../../domains/quality-loop/useTestDesignGeneration'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../../../shared/i18n/messages'
import { AutomationScriptReviewPanel } from './AutomationScriptReviewPanel'

const limits: { field: BudgetField; label: MessageKey; min: number; max: number; step: string }[] = [
  { field: 'input', label: 'Maximum input tokens', min: 512, max: 1000000, step: '1' },
  { field: 'output', label: 'Maximum output tokens', min: 512, max: 32768, step: '1' },
  { field: 'tokens', label: 'Total token reservation ceiling', min: 1024, max: 64000000, step: '1' },
  { field: 'cost', label: 'Maximum reserved spend', min: 0.000000001, max: 9000000, step: '0.000000001' },
]
export function AutomationScriptPanel({ draft, mapping, sessionId, onFailure }: {
  draft: GenerationArchive; mapping: RecordedMappingArchive; sessionId: string; onFailure: () => void
}) {
  const { t, tx } = useI18n(), state = useAutomationScripts(draft, mapping, sessionId, onFailure)
  const preview = state.prepared?.value, result = state.result
  return <section className="test-design-generation" aria-label={t('Pinned automation script drafts')}>
    <button className="small-btn" type="button" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect script drafts')}</button>
    {state.open && <>
      <p>{t('A project administrator must separately approve one complete model call. DSL drafts preserve reviewed cases and oracles; they cannot run a target.')}</p>
      <button className="small-btn" type="button" disabled={state.write.isPending} onClick={state.reload}>{t('Reload script access and history')}</button>
      {state.busy && <p role="status">{t('Verifying script history and source access...')}</p>}
      {state.failed && <p role="alert">{t('Script history could not be verified. Protected content is hidden; reload to check current access.')}</p>}
      {state.commandId && <p>{t('Original script command')}<code>{state.commandId}</code></p>}
      {state.write.isError && <p role="alert">{t('Script generation was not acknowledged. Inspect the original command history before a new confirmation. Unknown calls are never automatically resent.')}</p>}
      {state.rows && <>
        <label>{t('Script generation history')}<select value={state.selected} disabled={state.busy} onChange={(event) => state.choose(event.target.value)}>
          <option value="">{t('Choose a script command')}</option>{state.rows.map((item) => <option key={item.invocation_id} value={item.invocation_id}>{tx(item.status)} · {item.invocation_id}</option>)}</select></label>
        {state.history.hasNextPage && <button className="small-btn" type="button" disabled={state.busy} onClick={state.loadMore}>{t('Load more script history')}</button>}
        {state.history.hasNextPage && <p>{t('Load all history pages before confirming another generation; a running call may be outside this page.')}</p>}
        {state.item && <p>{state.item.provider_outcome_unknown ? t('Provider outcome is unknown. Its reservation is retained and the call will never be automatically resent.')
          : state.item.reply_archived ? t('Native reply archived; this does not imply a valid draft or verified coverage.') : t('No native call has been reserved.')}</p>}
        {!state.current && <p>{t('The original input is stale or withdrawn. Historical scripts remain inspectable; new generation and review are blocked.')}</p>}
        {state.current && !state.busy && !state.admitted && <p role="status">{t('Independently approve these exact cases before generating scripts. Mapping acceptance alone is not case admission.')}</p>}
        {state.admitted && <p>{t('Current case admission verified. Model egress and target execution still require separate authorization.')}</p>}
        <fieldset disabled={state.busy || !state.current || state.active}>
          <legend>{t('Native script generation budget')}</legend>
          <label>{t('HTTP script protocol')}<select value={state.protocol} onChange={(event) => state.chooseProtocol(event.target.value)}>
            <option value="v1">{t('v1: fixed request paths')}</option><option value="v2">{t('v2: response resource bindings')}</option>
            <option value="v3">{t('v3: original fixture resource imports')}</option></select></label>
          <p>{t('Response bindings locate resources only. They cannot replace independent expected results or authorize execution.')}</p>
          <label>{t('Tested chat model')}<select value={state.model} onChange={(event) => state.chooseModel(event.target.value)}>
            <option value="">{t('Choose a tested model')}</option>{state.choices.map((choice) => <option key={choice.config_id} value={choice.config_id}>{choice.display_name}</option>)}</select></label>
          {state.models.isError && <p role="alert">{t('Model choices are unavailable. Reopen this view to check access.')}</p>}
          <label>{t('Budget currency')}<select value={state.fields.currency} onChange={(event) => state.editBudget('currency', event.target.value)}>
            {['USD', 'CNY'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <div className="scope-grid">{limits.map((limit) => <label key={limit.field}>{t(limit.label)}<input type="number" value={state.fields[limit.field]}
            min={limit.min} max={limit.max} step={limit.step} onChange={(event) => state.editBudget(limit.field, event.target.value)} /></label>)}</div>
          <p>{t('Enter your own ceilings. The backend requires an operator-pinned tokenizer and pricing policy; no prices or model capacity are guessed.')}</p>
          <button className="small-btn" type="button" disabled={!state.mayPreview} onClick={state.prepare}>{t('Preview complete script budget')}</button>
        </fieldset>
        {state.preview.isError && <p role="alert">{t('Script preview unavailable. Check administrator permission, current mapping, tested model and operator policy. No source was sent.')}</p>}
        {preview && <div className="scope-record">
          <strong>{t('Complete single-call preview; no source sent')}</strong>
          <dl><dt>{t('Destination')}</dt><dd>{preview.destination}</dd><dt>{t('Model')}</dt><dd>{preview.model_name}</dd>
            <dt>{t('HTTP script protocol')}</dt><dd>{preview.request.http_protocol ?? 'nasus.runner-http-execution.v1'}</dd>
            <dt>{t('Source bindings')}</dt><dd>{preview.request.execution.source_binding_ids.length}</dd><dt>{t('Planned model calls')}</dt><dd>1</dd>
            <dt>{t('Independent case admission')}</dt><dd><code>{preview.request.case_approval_revision_id}</code></dd>
            <dt>{t('Estimated input tokens')}</dt><dd>{preview.reservation.estimated_input_tokens}</dd>
            <dt>{t('Reserved tokens')}</dt><dd>{preview.reservation.reserved_tokens}</dd>
            <dt>{t('Reserved spend at operator ceilings')}</dt><dd>{preview.reservation.currency} {(preview.reservation.reserved_cost_nanos / 1e9).toFixed(9)}</dd></dl>
          <code>{preview.request.input_digest}</code><code>{preview.request.execution.plan_digest}</code>
          <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy} onChange={(event) => state.confirm(event.target.checked)} />
            {t('I confirm this exact script input, model destination, source inventory and single-call token/spend ceiling. Execution is not authorized.')}</label>
          <button className="small-btn primary" type="button" disabled={!state.canStart} onClick={state.start}>{t('Generate script drafts')}</button>
        </div>}
      </>}
      {result && <div className="scope-record" data-testid="automation-script-draft">
        <strong>{t('Archived DSL draft; not executable approval')}</strong><code>{result.metadata.script_revision_id}</code>
        <p>{t('HTTP script protocol')}: {result.result.proposal.http_protocol ?? 'nasus.runner-http-execution.v1'}</p>
        <p>{t('{scripts} scripts and {gaps} explicit gaps; automated, executed and passed counts remain zero.', { scripts: result.metadata.script_count, gaps: result.metadata.gap_count })}</p>
        {result.result.proposal.scripts.map((script) => <details key={script.case_id}><summary>{result.result.prepared.cases.find((c) => c.case_id === script.case_id)?.title} · {script.kind}</summary>
          <code>{script.case_id}</code><pre>{JSON.stringify(script.actions, null, 2)}</pre></details>)}
        {result.result.proposal.gaps.map((gap) => <p key={gap.case_id}><code>{gap.case_id}</code>{gap.description}</p>)}
        <AutomationScriptReviewPanel key={result.metadata.script_revision_id + result.metadata.artifact_hash} draft={result} sessionId={sessionId} onFailure={onFailure} />
      </div>}
    </>}
  </section>
}
