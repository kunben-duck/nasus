import { useEffect } from 'react'
import { useMappingFinalization } from '../../../../../domains/quality-loop/useMappingFinalization'
import type { MappingWorkspace } from '../../../../../domains/quality-loop/types/mappingStaging'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ScopeText } from './ScopeInputs'

export function MappingFinalizationPanel({ workspace, changed, disabled, onFailure, onDone, onBusy }: {
  workspace: MappingWorkspace; changed: number; disabled: boolean; onFailure: () => void; onDone: () => void; onBusy: (busy: boolean) => void
}) {
  const { t } = useI18n(), state = useMappingFinalization(workspace, changed, onFailure, onDone)
  useEffect(() => { onBusy(state.busy); return () => onBusy(false) }, [state.busy, onBusy])
  return <fieldset disabled={disabled || state.busy} className="mapping-finalization" aria-label={t('Final mapping confirmation')}>
    <legend>{t('Final mapping confirmation')}</legend>
    <button type="button" className="small-btn" onClick={state.inspect}>{t('Inspect complete saved set')}</button>
    {state.busy && <p role="status">{t('Verifying every saved part before final confirmation...')}</p>}
    {state.write.isError && <p role="alert">{t('Final mapping was not acknowledged. Reload mapping history and confirm a fresh set; no automatic retry was sent.')}</p>}
    {state.view && <>
      <p>{t('{saved}/{total} parts saved; all {assertions} assertion pairs remain in scope.', {
        saved: state.view.saved_part_count, total: state.view.part_count, assertions: state.view.assertion_count })}</p>
      {!state.view.ready_for_confirmation && <p>{t('Save all parts under the current plan before final confirmation. No subset can be approved.')}</p>}
      {state.view.ready_for_confirmation && <>
        <code>{state.view.part_set!.part_set_digest}</code>
        <ScopeText label={t('Final review reason')} value={state.reason} onChange={state.explain} />
        <label className="context-pack-consent"><input type="checkbox" checked={state.confirmed} onChange={(e) => state.confirm(e.target.checked)} />
          {t('I independently confirm this exact complete saved set. This does not authorize automation or execution.')}</label>
        <button type="button" className="small-btn primary" disabled={!state.canSubmit} onClick={state.submit}>{t('Finalize complete mapping')}</button>
      </>}
    </>}
  </fieldset>
}
