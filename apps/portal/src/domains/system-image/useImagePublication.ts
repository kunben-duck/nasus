import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { imagePublicationApi, StalePublication, type PublicationPreview } from './imagePublicationApi'
import type { ImageReadScope } from './useImageRevisions'
import type { ImageRevisionSummary } from './types/imageRevision'

export function useImagePublication(scope: ImageReadScope, revision: ImageRevisionSummary) {
  const client = useQueryClient()
  const [open, setOpen] = useState(false), [baselineId, setBaselineId] = useState('')
  const [reason, setReason] = useState(''), [decision, setDecision] = useState<'approve' | 'reject'>('approve')
  const [consent, setConsent] = useState(''), [publishConsent, setPublishConsent] = useState('')
  const submitted = useRef(false)
  const { onFailure } = scope
  const query = useQuery({ queryKey: ['image-publications', scope.projectId, scope.sessionId, revision.image_revision_id, revision.artifact_hash, baselineId],
    enabled: open && !!baselineId, gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => imagePublicationApi.preview({ project_id: scope.projectId, image_revision_id: revision.image_revision_id,
      image_artifact_hash: revision.artifact_hash, target_baseline_id: baselineId }, signal) })
  const changed = query.error instanceof ApiRequestError && query.error.status === 409
  useEffect(() => { if (query.isError && !changed) onFailure(true) }, [query.isError, changed, onFailure])
  const write = useMutation({ retry: false, mutationFn: ({ view, action, attempt }: { view: PublicationPreview; action: 'review' | 'publish'; attempt: string }) =>
    imagePublicationApi.write(view, action, decision, reason, attempt),
    onSuccess: (_, { action }) => {
      void query.refetch()
      if (action === 'publish') void client.invalidateQueries({ queryKey: ['system-image', scope.projectId], exact: true })
    }, onSettled: () => { setConsent(''); setPublishConsent(''); submitted.current = false } })
  const view = !query.isFetching && !query.isError ? query.data : undefined
  const key = JSON.stringify([view?.preview_digest, view?.review?.review_id, query.dataUpdatedAt, decision, reason])
  const confirmed = !!view && consent === key, publishConfirmed = !!view && publishConsent === key
  const editable = !!view?.can_review && !write.isPending && !write.isError
  const canReview = editable && confirmed && !!reason.trim()
  const canPublish = editable && publishConfirmed && view?.review?.decision === 'approve' && view.head?.image_revision_id !== revision.image_revision_id
  function submit(action: 'review' | 'publish') {
    if (!view || submitted.current || !(action === 'review' ? canReview : canPublish)) return
    submitted.current = true; setConsent(''); setPublishConsent('')
    write.mutate({ view, action, attempt: crypto.randomUUID() })
  }
  function reset() { setConsent(''); setPublishConsent(''); write.reset() }
  return { open, baselineId, reason, decision, query, write, view, confirmed, publishConfirmed, canReview, canPublish,
    stale: changed || write.error instanceof StalePublication,
    toggle: () => { setOpen(!open); reset() },
    choose: (value: string) => { setBaselineId(value); reset() },
    explain: (value: string) => { setReason(value); reset() },
    decide: (value: 'approve' | 'reject') => { setDecision(value); reset() },
    confirm: (checked: boolean) => setConsent(checked ? key : ''),
    confirmPublish: (checked: boolean) => setPublishConsent(checked ? key : ''),
    reload: () => { reset(); void query.refetch() }, submit }
}
