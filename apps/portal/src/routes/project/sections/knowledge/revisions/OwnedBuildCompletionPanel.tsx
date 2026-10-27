import { useId } from 'react'
import type { BuildReviewHandoff } from '../../../../../domains/system-image/buildReviewHandoff'
import type { BuildCompletionObservation } from '../../../../../domains/system-image/types/buildCompletion'
import type { GapOwnershipView } from '../../../../../domains/system-image/types/buildGapOwnership'
import { useOwnedBuildCompletion } from '../../../../../domains/system-image/useOwnedBuildCompletion'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function OwnedBuildCompletionPanel({ review, completion, view }: {
  review: BuildReviewHandoff; completion: BuildCompletionObservation; view: GapOwnershipView
}) {
  const { t } = useI18n(), id = useId()
  const state = useOwnedBuildCompletion(review, completion, view, id)
  const report = state.observation?.report
  return <section className="image-revision-status" aria-labelledby={id}>
    <div className="image-row-heading"><strong id={id}>{t('Completion with confirmed responsibilities')}</strong>
      <button type="button" disabled={state.busy || !state.started && (state.unavailable
        || view.gaps.some((gap) => gap.ownership_status !== 'confirmed'))}
        onClick={state.started ? state.reload : () => void state.assess()}>
        {state.started ? t('Reload responsibility-pinned assessment') : t('Assess with this responsibility revision')}
      </button></div>
    <p>{t('This creates a separate assessment pinned to this confirmed revision. Original reports remain unchanged; assigned gaps are still unresolved.')}</p>
    {state.busy && <p role="status">{t('Verifying the fixed responsibility revision and original build...')}</p>}
    {state.unavailable && <p role="alert">{t('The responsibility-pinned assessment could not be verified. Reload reads the original command only; it never resubmits.')}</p>}
    {state.observation && !report && <p role="status">{['pending', 'running'].includes(state.observation.command.status)
      ? t('The original completion assessment is still running.') : t('The original assessment stopped without a verified report. It was not restarted.')}</p>}
    {report && <div data-testid="owned-build-completion-report">
      <p><strong>{t('Candidate delivery is blocked')}</strong></p>
      <dl className="build-completion-metrics">
        <div><dt>{t('Pinned responsibility revision')}</dt><dd><code>{report.ownership.revision_id}</code></dd></div>
        <div><dt>{t('Confirmed gap responsibilities')}</dt><dd>{report.ownership.assignment_count}</dd></div>
      </dl>
      <p>{t('Full-plan spend and critical conflicts remain unverified. Confirmed owners do not authorize delivery, publication or execution.')}</p>
      <ul className="build-completion-blockers">{report.blockers.map((code) => <li key={code}><code>{code}</code></li>)}</ul>
    </div>}
  </section>
}
