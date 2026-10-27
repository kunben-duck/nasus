import { useId } from 'react'
import type { BuildReviewHandoff } from '../../../../../domains/system-image/buildReviewHandoff'
import type { BuildCompletionObservation } from '../../../../../domains/system-image/types/buildCompletion'
import { useBuildGapOwnership } from '../../../../../domains/system-image/useBuildGapOwnership'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { OwnedBuildCompletionPanel } from './OwnedBuildCompletionPanel'

export function BuildGapOwnershipPanel({ review, completion }: { review: BuildReviewHandoff; completion: BuildCompletionObservation }) {
  const { t, tx } = useI18n(), id = useId()
  const state = useBuildGapOwnership(review, completion, id)
  const busy = state.checking || state.sending
  const pending = state.command?.status === 'waiting_confirmation'
  const submitted = state.command?.input_payload.assignments as { gap_id: string; owner_actor_id: string; reason: string }[] | undefined
  const valid = Boolean(state.owners) && state.assignments.length > 0 && state.assignments.every((item) =>
    state.owners!.some((owner) => owner.actor_id === item.owner_actor_id) && item.reason.trim() && item.reason.length <= 1000)
  return <section className="image-revision-status build-gap-ownership" aria-labelledby={id}>
    <div className="image-row-heading"><strong id={id}>{t('Build gap responsibilities')}</strong>
      <button type="button" disabled={busy} onClick={state.reload}>{t('Reload responsibilities')}</button></div>
    <p>{t('Responsibilities are recorded separately. Assigning an owner does not resolve a gap, change the original assessment, complete the goal or authorize publication.')}</p>
    {busy && <p role="status">{t('Verifying gap responsibilities...')}</p>}
    {(state.inaccessible || state.uncertain) && <p role="alert">{t('The original responsibility command or history could not be verified. Previous results are hidden; reload only reads the original records.')}</p>}
    {state.view && !state.uncertain && <div data-testid="build-gap-responsibilities">
      <ul className="link-candidate-list">{state.view.gaps.map((gap) => <li key={gap.gap_id}>
        <strong><code>{gap.code}</code></strong><p>{tx(gap.required_action)}</p>
        <p>{t('Gap owner')}: {gap.owner_actor_id ?? t('Owner not assigned')}
          {gap.ownership_status === 'owner_unavailable' && <> · {t('Owner is no longer available')}</>}</p>
        <p>{t('Gap remains unresolved')}</p>
      </li>)}</ul>
      {!state.editing && !pending && !['pending', 'running'].includes(state.command?.status ?? '') &&
        <button type="button" onClick={state.edit}>{t('Assign or reassign owners')}</button>}
      {state.editing && <form onSubmit={(event) => { event.preventDefault(); void state.prepare() }}>
        {state.ownersUnavailable && <p role="alert">{t('Eligible project members could not be verified. No assignment can be prepared.')}</p>}
        <ul className="link-candidate-list">{state.assignments.map((assignment, index) => <li key={assignment.gap_id}>
          <strong><code>{state.view!.gaps[index].code}</code></strong>
          <label>{t('Gap owner')}<select value={assignment.owner_actor_id} disabled={!state.owners}
            onChange={(event) => state.setAssignments((items) => items.map((item, i) => i === index ? { ...item, owner_actor_id: event.target.value } : item))}>
            <option value="">{t('Select a project member')}</option>
            {state.owners?.map((owner) => <option key={owner.actor_id} value={owner.actor_id}>{owner.display_name} · {owner.actor_id}</option>)}
          </select></label>
          <label>{t('Responsibility reason')}<textarea value={assignment.reason} maxLength={1000}
            onChange={(event) => state.setAssignments((items) => items.map((item, i) => i === index ? { ...item, reason: event.target.value } : item))} /></label>
        </li>)}</ul>
        <div className="image-row-heading"><button type="button" onClick={state.cancelEdit}>{t('Cancel')}</button>
          <button type="submit" disabled={!valid || busy}>{t('Prepare responsibility confirmation')}</button></div>
      </form>}
      {pending && <div className="image-source-document">
        <p>{t('Review the exact owners and reasons below, then confirm separately. Reloading this page does not confirm.')}</p>
        <ul className="link-candidate-list">{submitted?.map((item) => <li key={item.gap_id}>
          <strong><code>{state.view!.gaps.find((gap) => gap.gap_id === item.gap_id)!.code}</code></strong>
          <p>{t('Gap owner')}: {item.owner_actor_id}</p><p>{item.reason}</p>
        </li>)}</ul>
        <button type="button" onClick={() => void state.confirm()}>{t('Confirm gap responsibilities')}</button>
      </div>}
      {state.command?.status === 'completed' && <p role="status">{t('Responsibilities saved; all original gaps remain unresolved.')}</p>}
      {['pending', 'running'].includes(state.command?.status ?? '') && <p role="status">{t('The original responsibility command is still running.')}</p>}
      {['failed', 'cancelled'].includes(state.command?.status ?? '') && <p role="alert">{t('The original responsibility command stopped. It was not restarted.')}</p>}
      {!!state.view.history.length && <details><summary>{t('Responsibility revision history')}</summary>
        <ul className="link-candidate-list">{state.view.history.map((revision) => <li key={revision.revision_id}>
          <strong>{revision.revision_number} · <code>{revision.revision_id}</code></strong>
          <p>{revision.created_at} · {revision.confirmed_by}</p>
          {revision.assignments.map((item) => <p key={item.gap_id}>{state.view!.gaps.find((gap) => gap.gap_id === item.gap_id)!.code}: {item.owner_actor_id} · {item.reason}</p>)}
        </li>)}</ul>
      </details>}
      {!!state.view.history.length && <OwnedBuildCompletionPanel review={review} completion={completion} view={state.view} />}
    </div>}
  </section>
}
