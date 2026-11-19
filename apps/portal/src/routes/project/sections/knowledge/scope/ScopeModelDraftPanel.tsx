import type { ContextArchive } from '../../../../../domains/system-image/types/contextPack'
import { useScopeDraft } from '../../../../../domains/quality-loop/useScopeDraft'
import { scopeDraftForReview, type ScopeModelDraft } from '../../../../../domains/quality-loop/scopeDraftApi'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../../../shared/i18n/messages'
import type { BudgetField } from '../../../../../domains/quality-loop/useTestDesignGeneration'
import { ScopeContractEditor } from './ScopeContractEditor'
import { useAuthUser } from '../../../../../domains/platform/useAuthSession'

const fields: { field: BudgetField; label: MessageKey }[] = [
  { field: 'input', label: 'Maximum input tokens' }, { field: 'output', label: 'Maximum output tokens' },
  { field: 'tokens', label: 'Total token reservation ceiling' }, { field: 'cost', label: 'Maximum reserved spend' },
]
type Props = {
  context: ContextArchive; sessionId: string; onReview: (draft: ScopeModelDraft) => void
}
export function ScopeModelDraftPanel(props: Props) {
  const actor = useAuthUser()
  if (!actor.data || actor.isError) return null
  return <ScopeDraftPanel key={`${actor.data.id}:${props.sessionId}:${props.context.metadata.context_id}:${props.context.metadata.artifact_hash}`}
    {...props} actorId={actor.data.id} />
}
function ScopeDraftPanel({ context, sessionId, onReview, actorId }: Props & { actorId: string }) {
  const { t, tx } = useI18n(), state = useScopeDraft(context, sessionId, actorId), value = state.originalValue ?? (!state.stored.attempt ? state.prepared?.value : undefined)
  return <section className="scope-record" aria-label={t('Model scope draft')}>
    <h4>{t('Model scope draft')}</h4><p>{t('Generate suggestions from all confirmed requirements. An independent reviewer must approve the scope before case generation.')}</p>
    <fieldset disabled={!state.editable}>
      <legend>{t('Native generation budget')}</legend>
      <label>{t('Tested chat model')}<select value={state.model} onChange={(event) => state.chooseModel(event.target.value)}>
        <option value="">{t('Choose a tested model')}</option>{state.choices.map((item) => <option key={item.config_id} value={item.config_id}>{item.display_name}</option>)}</select></label>
      <label>{t('Budget currency')}<select value={state.fields.currency} onChange={(event) => state.editBudget('currency', event.target.value)}>
        {['USD', 'CNY'].map((currency) => <option key={currency} value={currency}>{currency}</option>)}</select></label>
      <div className="scope-grid">{fields.map(({ field, label }) => <label key={field}>{t(label)}<input type="number" min="0" step="any"
        value={state.fields[field]} onChange={(event) => state.editBudget(field, event.target.value)} /></label>)}</div>
      <p>{t('Enter your own ceilings. The backend requires an operator-pinned tokenizer and pricing policy; no prices or model capacity are guessed.')}</p>
      <button type="button" className="small-btn" disabled={!state.mayPreview} onClick={state.prepare}>{t('Preview scope draft budget')}</button>
    </fieldset>
    {value && <div className="scope-record"><dl><dt>{t('Model')}</dt><dd>{value.model_name}</dd>
      <dt>{t('Destination')}</dt><dd>{value.destination}</dd><dt>{t('Source bindings')}</dt><dd>{value.plan.source_binding_ids.length}</dd>
      <dt>{t('Reserved tokens')}</dt><dd>{value.plan.reservation.reserved_tokens}</dd>
      <dt>{t('Reserved spend at operator ceilings')}</dt><dd>{value.plan.reservation.currency} {(value.plan.reservation.reserved_cost_nanos / 1e9).toFixed(9)}</dd></dl>
      <label><input type="checkbox" disabled={state.busy} checked={state.originalValue ? state.originalConfirmed : state.confirmed}
        onChange={(event) => state.originalValue ? state.confirmOriginal(event.target.checked) : state.confirm(event.target.checked)} />
        {t('I confirm this exact model destination, full source inventory and maximum token/spend reservation for one draft generation call.')}</label>
      <button type="button" className="small-btn primary" disabled={state.originalValue ? !state.mayResume : !state.canStart}
        onClick={state.originalValue ? state.resumeOriginal : state.start}>{t('Generate scope draft')}</button></div>}
    {state.stored.attempt && <p role="status">{t('Scope draft recovery only reads the original command. It never resends model calls or restores consent.')}</p>}
    {state.original && <p>{tx(state.original.command.status)} <code>{state.original.command.id}</code></p>}
    {state.original?.command.status === 'waiting_confirmation' && <button type="button" className="small-btn" disabled={state.busy}
      onClick={state.verifyOriginal}>{t('Verify original scope budget')}</button>}
    {state.mayClear && <button type="button" className="small-btn" onClick={state.another}>{t('Prepare another scope draft')}</button>}
    {(state.stored.invalid || state.recovery.isError || state.originalPreview.isError || state.resume.isError)
      && <p role="alert">{t('Scope command recovery is blocked. Keep the original request; do not submit another generation.')}</p>}
    {(state.preview.isError || state.models.isError) && <p role="alert">{t('Generation preview unavailable. Check administrator permission, current scope, tested model and operator tokenizer/pricing policy. No source was sent.')}</p>}
    {state.write.isPending && <p role="status">{t('Generating scope suggestions; this does not approve the scope.')}</p>}
    {state.write.isError && <p role="alert">{t('The command was not acknowledged. Inspect refreshed history before any new confirmation; no automatic retry was sent.')}</p>}
    {(state.history.isError || state.archive.isError) && <p role="alert">{t('Generation history or result could not be verified. Protected content is hidden; reload to check access.')}</p>}
    <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload model scope history')}</button>
    {!!state.rows?.length && <label>{t('Model scope draft')}<select value={state.selected} disabled={state.busy} onChange={(event) => state.choose(event.target.value)}>
      <option value="">{t('Select a draft')}</option>{state.rows.map((item) => <option key={item.invocation_id} value={item.invocation_id}>{tx(item.status)} · {item.recorded_at}</option>)}</select></label>}
    {state.result && <><ScopeContractEditor context={context.context} value={scopeDraftForReview(state.result, context)} readOnly onChange={() => {}} />
      <button type="button" className="small-btn" disabled={!state.result.current_use.context_current || state.busy}
        onClick={() => onReview(state.result!)}>{t('Review this model suggestion')}</button></>}
  </section>
}
