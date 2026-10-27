import type { ScopeArchive } from '../../../../../domains/quality-loop/types/testDesignScope'
import { useTestDesignGeneration, type BudgetField } from '../../../../../domains/quality-loop/useTestDesignGeneration'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../../../shared/i18n/messages'
import { TestDesignMappingPanel } from './TestDesignMappingPanel'
import { ArchivedDraftCases } from './ArchivedDraftCases'

const limits: { field: BudgetField; label: MessageKey; min: number; max: number; step: string }[] = [
  { field: 'calls', label: 'Maximum model calls', min: 1, max: 64, step: '1' },
  { field: 'input', label: 'Maximum input tokens', min: 512, max: 1000000, step: '1' },
  { field: 'output', label: 'Maximum output tokens', min: 512, max: 32768, step: '1' },
  { field: 'tokens', label: 'Total token reservation ceiling', min: 1024, max: 64000000, step: '1' },
  { field: 'cost', label: 'Maximum reserved spend', min: 0.000000001, max: 9000000, step: '0.000000001' },
]
export function TestDesignGenerationPanel({ scope, sessionId }: { scope: ScopeArchive; sessionId: string }) {
  const { t, tx } = useI18n(), state = useTestDesignGeneration(scope, sessionId)
  const preview = state.prepared?.preview, job = state.job, result = state.result
  return <section className="test-design-generation" aria-label={t('Pinned draft test generation')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={state.busy} onClick={state.toggle}>{t('Inspect draft generation')}</button>
    {state.open && <>
      <p>{t('A project administrator must separately confirm the model destination, complete source input and token/cost ceilings. Drafts are not reviewed mappings or executed tests.')}</p>
      <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload generation access and history')}</button>
      {(state.history.isFetching || state.jobQuery.isFetching || state.archive.isFetching) && <p role="status">{t('Verifying generation history and current source access...')}</p>}
      {(state.history.isError || state.jobQuery.isError || state.archive.isError) && <p role="alert">{t('Generation history or result could not be verified. Protected content is hidden; reload to check access.')}</p>}
      {state.mappingFailed && <p role="alert">{t('Mapping access or integrity could not be verified. The draft and mapping are hidden; reload generation access before continuing.')}</p>}
      {(state.write.isError || state.cancel.isError || state.recovery.isError) && <p role="alert">{t('The command was not acknowledged. Inspect refreshed history before any new confirmation; no automatic retry was sent.')}</p>}
      {state.rows && <>
        {!state.current && <p>{t('This scope is incomplete, withdrawn or stale. Historical drafts remain inspectable, but new generation is blocked.')}</p>}
        <fieldset disabled={state.busy || !state.current || !!state.active}>
          <legend>{t('Native generation budget')}</legend>
          <label>{t('Tested chat model')}<select value={state.model} onChange={(event) => state.chooseModel(event.target.value)}>
            <option value="">{t('Choose a tested model')}</option>{state.choices.map((choice) => <option key={choice.config_id} value={choice.config_id}>{choice.display_name}</option>)}
          </select></label>
          {state.models.isError && <p role="alert">{t('Model choices are unavailable. Reopen this view to check access.')}</p>}
          {!state.models.isFetching && !state.models.isError && !state.choices.length && <p>{t('No eligible models. Add and test a custom LLM in Model configuration; legacy models must be retested.')}</p>}
          <label>{t('Budget currency')}<select value={state.fields.currency} onChange={(event) => state.editBudget('currency', event.target.value)}>
            {['USD', 'CNY'].map((currency) => <option key={currency} value={currency}>{currency}</option>)}</select></label>
          <div className="scope-grid">{limits.map((limit) => <label key={limit.field}>{t(limit.label)}<input type="number" value={state.fields[limit.field]}
            min={limit.min} max={limit.max} step={limit.step} onChange={(event) => state.editBudget(limit.field, event.target.value)} /></label>)}</div>
          <p>{t('Enter your own ceilings. The backend requires an operator-pinned tokenizer and pricing policy; no prices or model capacity are guessed.')}</p>
          <button type="button" className="small-btn" disabled={!state.mayPreview} onClick={state.prepare}>{t('Preview complete generation budget')}</button>
        </fieldset>
        {state.preview.isPending && <p role="status">{t('Checking complete input, model policy and current authority; no source sent...')}</p>}
        {state.preview.isError && <p role="alert">{t('Generation preview unavailable. Check administrator permission, current scope, tested model and operator tokenizer/pricing policy. No source was sent.')}</p>}
        {preview && <div className="scope-record">
          <strong>{preview.batch_planning ? t('Complete batch preview; no source sent') : t('Complete single-call preview; no source sent')}</strong>
          <dl><dt>{t('Destination')}</dt><dd>{preview.destination}</dd><dt>{t('Model')}</dt><dd>{preview.model_name}</dd>
            <dt>{t('Source bindings')}</dt><dd>{preview.request.execution.source_binding_ids.length}</dd>
            <dt>{t('Planned model calls')}</dt><dd>{preview.call_count}</dd>
            <dt>{t('Estimated input tokens')}</dt><dd>{preview.reservation.estimated_input_tokens}</dd>
            <dt>{t('Reserved tokens')}</dt><dd>{preview.reservation.reserved_tokens}</dd>
            <dt>{t('Reserved spend at operator ceilings')}</dt><dd>{preview.reservation.currency} {(preview.reservation.reserved_cost_nanos / 1e9).toFixed(9)}</dd>
            <dt>{t('Tokenizer')}</dt><dd>{preview.policy.tokenizer_id}</dd></dl>
          <code>{preview.request.execution.plan_digest}</code>
          <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} disabled={state.busy || !!state.active} onChange={(event) => state.confirm(event.target.checked)} />
            {preview.batch_planning ? t('I confirm this exact complete batch plan, model destination, source inventory and cumulative token/spend ceilings.')
              : t('I confirm this exact model destination, full source inventory and maximum token/spend reservation for one draft generation call.')}</label>
          <button type="button" className="small-btn primary" disabled={!state.canStart} onClick={state.start}>{t('Generate draft cases')}</button>
        </div>}
        {!!state.rows.length && <label>{t('Generation history')}<select value={state.selected} disabled={state.busy} onChange={(event) => state.chooseJob(event.target.value)}>
          {state.rows.map((row) => <option key={row.id} value={row.id}>{tx(row.status)} · {row.id}</option>)}</select></label>}
        {state.runningOutsidePage && <p role="status">{t('A generation task is running outside the loaded history. Load more records to inspect it.')}</p>}
        {state.history.hasNextPage && <button type="button" className="small-btn" disabled={state.busy || state.history.isFetching} onClick={state.loadMore}>
          {t('Load more generation history')}</button>}
      </>}
      {job && <div className="scope-record" aria-label={t('Generation task status')}>
        <strong>{tx(job.status)}</strong><code>{job.invocation_id}</code>
        {job.batch_progress && <dl><dt>{t('Planned model calls')}</dt><dd>{job.batch_progress.call_count}</dd>
          <dt>{t('Archived batches')}</dt><dd>{job.batch_progress.archived_calls}</dd>
          <dt>{t('Unknown batch outcomes')}</dt><dd>{job.batch_progress.unknown_calls}</dd>
          <dt>{t('Unstarted batches')}</dt><dd>{job.batch_progress.unstarted_calls}</dd></dl>}
        <p>{job.reply_archived ? t('Native reply archived; this does not imply a valid draft or verified coverage.')
          : job.batch_progress && !job.provider_outcome_unknown && job.call_reserved ? t('Archived batches are retained. Remaining batches have not all completed; no partial draft is published.')
          : job.provider_outcome_unknown ? t('Provider outcome is unknown. Its reservation is retained and the call will never be automatically resent.') : t('No native call has been reserved.')}</p>
        {(job.status === 'running' || job.recovery_request) && <>
          <label className="context-pack-consent"><input type="checkbox" checked={state.controlConfirmed} disabled={state.busy} onChange={(event) => state.confirmControl(event.target.checked)} />
            {job.status === 'running' ? t('I confirm stopping this exact job; charged or unknown calls are not refunded or resent.')
              : job.batch_progress ? t('I confirm recovering this exact complete set of archived batch replies in a new command, without another model request.')
              : t('I confirm recovering this exact archived reply in a new command, without another model request.')}</label>
          {job.status === 'running' ? <button type="button" className="small-btn" disabled={!state.controlConfirmed || state.busy || !state.cancel.isIdle} onClick={state.stop}>{t('Stop generation')}</button>
            : <button type="button" className="small-btn" disabled={!state.controlConfirmed || state.busy || !state.current || !state.recovery.isIdle} onClick={state.resume}>{t('Recover archived draft')}</button>}
        </>}
      </div>}
      {result && <ArchivedDraftCases draft={result}>
        <TestDesignMappingPanel key={result.metadata.generation_id + result.metadata.artifact_hash} draft={result} sessionId={sessionId} onFailure={state.onMappingFailure} />
      </ArchivedDraftCases>}
    </>}
  </section>
}
