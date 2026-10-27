import { useAuthUser } from '../../../../../domains/platform/useAuthSession'
import { useTestDesignReviewQueue } from '../../../../../domains/quality-loop/useTestDesignReviewQueue'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'
import { ArchivedDraftCases } from './ArchivedDraftCases'
import { TestDesignMappingPanel } from './TestDesignMappingPanel'
import './test-design-scope.css'
import './test-design-review-queue.css'

export function TestDesignReviewQueue({ projectId }: { projectId: string }) {
  const { t } = useI18n(), user = useAuthUser(), state = useTestDesignReviewQueue(projectId, user.data?.id ?? '')
  return <section className="test-design-scope test-design-generation test-design-review-queue" aria-label={t('Draft mapping review queue')}>
    <button type="button" className="small-btn" aria-expanded={state.open} disabled={!user.data} onClick={state.toggle}>{t('Review draft cases')}</button>
    {state.open && <>
      <p>{t('Project reviewers can inspect archived drafts without model egress or generation permissions. Mapping review does not prove execution.')}</p>
      <button type="button" className="small-btn" disabled={state.list.isFetching} onClick={state.reload}>{t('Reload review drafts')}</button>
      {(state.list.isFetching || state.detail.isFetching) && <p role="status">{t('Verifying review drafts and their original source permissions...')}</p>}
      {state.failed && <p role="alert">{t('Draft review access or integrity could not be verified. The list, draft and mapping are hidden; reload to check reviewer and source access.')}</p>}
      {state.rows && <>
        {!state.rows.length && <p>{t('No archived drafts are available for this project.')}</p>}
        <div className="review-draft-options">{state.rows.map((item) => <button type="button" className="small-btn" key={item.metadata.generation_id}
          aria-pressed={state.selected === item.metadata.generation_id} onClick={() => state.choose(item.metadata.generation_id)}>
          {t('Inspect draft {id} ({cases} cases)', { id: item.metadata.generation_id, cases: item.metadata.case_count })}</button>)}</div>
        {state.list.hasNextPage && <button type="button" className="small-btn" onClick={state.loadMore}>{t('Load more review drafts')}</button>}
      </>}
      {state.draft && user.data && <ArchivedDraftCases key={state.draft.metadata.generation_id + state.detail.dataUpdatedAt} draft={state.draft}>
        <TestDesignMappingPanel draft={state.draft} sessionId={user.data.id} onFailure={state.onMappingFailure} />
      </ArchivedDraftCases>}
    </>}
  </section>
}
