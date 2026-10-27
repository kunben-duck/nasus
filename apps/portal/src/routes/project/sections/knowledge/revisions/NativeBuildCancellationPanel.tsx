import type { ImageReadScope } from '../../../../../domains/system-image/useImageRevisions'
import type { NativeBuildCommand } from '../../../../../domains/quality-loop/types/nativeBuilds'
import { useNativeBuildCancellation } from '../../../../../domains/quality-loop/useNativeBuildCancellation'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function NativeBuildCancellationPanel({ scope, actorId, targetId, input, status, sourceRead, reloadTarget }: {
  scope: ImageReadScope; actorId: string; targetId: string; input: NativeBuildCommand; status: string; sourceRead: number; reloadTarget: () => void
}) {
  const { t, tx } = useI18n(), state = useNativeBuildCancellation(scope, actorId, targetId, input, status, sourceRead, reloadTarget)
  if (!state.visible) return null
  return <section className="scope-record" aria-label={t('Independent native build cancellation')}>
    <strong>{t('Independent native build cancellation')}</strong><code>{targetId}</code>
    <p>{t('Cancel only this original build. Saved artifacts remain intact; requesting cancellation does not prove that worker resources have been cleaned up.')}</p>
    {state.busy && <p role="status">{t('Verifying original cancellation...')}</p>}
    {state.error && <p role="alert">{t('Cancellation acknowledgement is unknown. Reload only reads the original cancellation; it never resends or confirms it automatically.')}</p>}
    {state.original && <div data-testid="native-build-original-cancellation"><code>{state.original.command.id}</code><span>{tx(state.original.command.status)}</span></div>}
    {state.original?.receipt && <p data-testid="native-build-cancellation-receipt">{state.original.receipt.cancellation_requested
      ? t('Cancellation recorded; resource cleanup remains unverified.') : t('The original build was already terminal. No saved artifact was removed.')}</p>}
    {state.original && ['failed', 'cancelled'].includes(state.original.command.status) && <p>{t('The original cancellation did not complete. Preparing another request requires fresh independent confirmation and does not restart the build.')}</p>}
    {state.eligible && <label className="context-pack-consent"><input type="checkbox" checked={state.checked} onChange={(event) => state.check(event.target.checked)} />
      <span>{t('I independently confirm cancellation of this exact original build, without deleting any saved artifact or authorizing another build.')}</span></label>}
    {state.eligible && <button type="button" className="small-btn" disabled={!state.checked} onClick={state.cancel}>
      {state.original ? t('Confirm original cancellation') : t('Cancel original native build')}</button>}
    {state.error || state.original || state.busy ? <button type="button" className="small-btn" disabled={state.busy} onClick={state.reload}>{t('Reload original cancellation')}</button> : null}
    {state.mayPrepareAnother && <button type="button" className="small-btn" onClick={state.prepareAnother}>{t('Prepare another independently confirmed cancellation')}</button>}
  </section>
}
