import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { referenceReviewApi, type ReviewPage } from '../../../../../domains/system-image/referenceReviewApi'
import { useI18n } from '../../../../../shared/i18n/I18nProvider'

export function FreezeReferenceReview({ page, parentArtifactHash }: { page: ReviewPage; parentArtifactHash: string }) {
  const { t } = useI18n()
  const [confirmed, setConfirmed] = useState(false)
  const mutation = useMutation({ mutationFn: () => referenceReviewApi.freeze(page, parentArtifactHash) })
  return <form className="freeze-reference-review" onSubmit={(event) => {
    event.preventDefault()
    if (confirmed && !mutation.isPending && !mutation.isSuccess && !mutation.isError) mutation.mutate()
  }}>
    <p>{t('Freeze the current review into a new candidate. Later decisions will not change it; this does not publish the image.')}</p>
    <label className="reference-review-confirm"><input type="checkbox" checked={confirmed}
      disabled={mutation.isPending || mutation.isSuccess} onChange={(event) => setConfirmed(event.target.checked)} />
      {t('Confirm freezing this exact decision and parent revision.')}</label>
    <button type="submit" disabled={!confirmed || mutation.isPending || mutation.isSuccess || mutation.isError}>{t('Freeze as new candidate')}</button>
    {mutation.isSuccess && <p role="status">{t('Candidate frozen. Reopen Image revisions to inspect Frozen reviews.')} <code>{mutation.data}</code></p>}
    {mutation.isError && <p role="alert">{t('Reference operation failed. Check permission and reload before trying again.')}</p>}
  </form>
}
