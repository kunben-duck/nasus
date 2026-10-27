import { useAuthUser } from '../../../../../domains/platform/useAuthSession'
import { useHttpFixtureHistory } from '../../../../../domains/quality-loop/useHttpFixtureHistory'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { HttpFixtureObservationDetails } from './HttpFixtureObservationDetails'
import './test-design-scope.css'
import './test-design-review-queue.css'
import './http-fixture-history.css'

export function HttpFixtureHistoryPanel({ projectId }: { projectId: string }) {
  const { t } = useI18n(), user = useAuthUser(), state = useHttpFixtureHistory(projectId, user.data?.id ?? '')
  const metadata = state.metadata
  return <section className="test-design-scope test-design-review-queue fixture-history" aria-label={t('Project test data operation history')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={!user.data} onClick={state.toggle}>{t('Find original test data operations')}</button>
    {state.open && <>
      <p>{t('Find original permission, execution and cancellation commands without this browser session. This view never confirms commands or resends requests.')}</p>
      <button type="button" className="small-btn" disabled={state.list.isFetching || state.detail.isFetching || state.journal.isFetching} onClick={state.reload}>{t('Reload test data history')}</button>
      {(state.list.isFetching || state.detail.isFetching || state.inspect && state.journal.isFetching) && <p role="status">{t('Verifying original commands and source access...')}</p>}
      {state.failed && <p role="alert">{t('Original command history changed or could not be verified. Protected metadata is hidden; reload to check current access and state.')}</p>}
      {state.rows && <>
        {!state.rows.length && <p>{t('No original test data operations are available for this project.')}</p>}
        <div className="review-draft-options">{state.rows.map((item) => <button type="button" className="small-btn" key={item.invocation_id}
          aria-pressed={state.selected === item.invocation_id} onClick={() => state.choose(item.invocation_id)}>
          {t('Inspect original command {id}', { id: item.invocation_id })}</button>)}</div>
        {state.list.hasNextPage && <button type="button" className="small-btn" disabled={state.list.isFetching} onClick={state.loadMore}>{t('Load more test data operations')}</button>}
      </>}
      {metadata && <div className="scope-record" data-testid="fixture-history-metadata">
        <strong>{t('Original fixture command')}</strong><code>{metadata.invocation_id}</code>
        <code>{metadata.stage}</code><code>{metadata.status}</code><code>{metadata.operation}</code>
        <p>{t('Fixture attempt ID')}: <code>{metadata.attempt_id}</code></p>
        <p>{t('Original fixture scope')}: <code>{metadata.recipe_id}</code></p>
        {metadata.original_execution_id && <p>{t('Original fixture execution command')}: <code>{metadata.original_execution_id}</code></p>}
        <p>{t('Command metadata is not a target observation. Expired permission stays historical; unknown effects must not be retried.')}</p>
        <button type="button" className="small-btn" disabled={state.journal.isFetching} onClick={state.inspectJournal}>{t('Inspect persisted operation phases')}</button>
      </div>}
      {state.observation && <HttpFixtureObservationDetails value={state.observation} />}
    </>}
  </section>
}
