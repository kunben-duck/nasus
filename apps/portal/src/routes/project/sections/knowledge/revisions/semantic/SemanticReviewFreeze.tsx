import { useSemanticFreeze } from '../../../../../../domains/system-image/useSemanticFreeze'
import type { SemanticReviewPage } from '../../../../../../domains/system-image/types/semanticReview'
import { useI18n } from '../../../../../../shared/i18n/I18nProvider'

export function SemanticReviewFreeze({ page }: { page: SemanticReviewPage }) {
  const { t } = useI18n()
  const state = useSemanticFreeze(page)
  return <section aria-label={t('Freeze semantic review')}>
    <p>{t('Freeze this exact decision into a new candidate. Later reviews will not change it; source authority and verified coverage remain unchanged.')}</p>
    <p>{t('Decision ID')}: <code>{page.head_decision_id}</code></p>
    <label className="semantic-confirm"><input type="checkbox" checked={state.confirmed} disabled={!state.write.isIdle}
      onChange={(event) => state.confirm(event.target.checked)} />{t('Confirm freezing this reviewed semantic relation as a new candidate.')}</label>
    <button className="small-btn" disabled={!state.canSubmit} onClick={state.submit}>{t('Freeze semantic review')}</button>
    {state.write.isPending && <p role="status">{t('Freezing reviewed membership...')}</p>}
    {state.write.isSuccess && <p role="status">{t('Semantic review frozen. Reopen the revision list to inspect the new candidate.')}
      <code>{state.write.data}</code></p>}
    {state.write.isError && <p role="alert">{state.stale
      ? t('Another reviewer changed this claim. Reload its history and explicitly confirm a new decision.')
      : t('Freeze was not acknowledged. Reload review history before retrying; no automatic retry was sent.')}</p>}
  </section>
}
