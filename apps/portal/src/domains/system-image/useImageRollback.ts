import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { imagePublicationApi, rollbackPolicy, StalePublication, type RollbackTarget } from './imagePublicationApi'
import { imageRollbackApi, type RollbackPreview } from './imageRollbackApi'
import type { ImageReadScope } from './useImageRevisions'

export function useImageRollback(scope: ImageReadScope) {
  const client = useQueryClient(), submitted = useRef(false)
  const [open, setOpen] = useState(false), [baselineId, setBaselineId] = useState(''), [after, setAfter] = useState(0)
  const [selectedId, setSelectedId] = useState(''), [reason, setReason] = useState(''), [decision, setDecision] = useState<'approve' | 'reject'>('approve')
  const [consent, setConsent] = useState(''), [restoreConsent, setRestoreConsent] = useState('')
  const history = useQuery({ queryKey: ['image-publications', scope.projectId, scope.sessionId, 'rollback-history', baselineId, after],
    enabled: open && !!baselineId, retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => imageRollbackApi.history(scope.projectId, baselineId, after, signal) })
  const page = !history.isFetching && !history.isError ? history.data : undefined
  const selected = page?.items.find((item) => item.publication_id === selectedId && page.head && item.sequence < page.head.sequence
    && item.image_revision_id !== page.head.image_revision_id)
  const target: RollbackTarget | undefined = selected && page?.head ? { project_id: scope.projectId, target_baseline_id: baselineId,
    image_revision_id: selected.image_revision_id, image_artifact_hash: selected.image_artifact_hash,
    expected_head_id: page.head.publication_id, rollback_publication_id: selected.publication_id, policy_revision: rollbackPolicy } : undefined
  const query = useQuery({ queryKey: ['image-publications', scope.projectId, scope.sessionId, 'rollback-preview', target, history.dataUpdatedAt],
    enabled: open && !!target, retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => { if (!target) throw new Error('Rollback selection missing'); return imageRollbackApi.preview(target, signal) } })
  const write = useMutation({ retry: false,
    mutationFn: ({ view, action, attempt }: { view: RollbackPreview; action: 'review' | 'publish'; attempt: string }) => imagePublicationApi.write(view, action, decision, reason, attempt),
    onSuccess: (_, { action }) => {
      void client.invalidateQueries({ queryKey: ['image-publications', scope.projectId] })
      if (action === 'publish') void client.invalidateQueries({ queryKey: ['system-image', scope.projectId], exact: true })
    }, onSettled: () => { submitted.current = false; setConsent(''); setRestoreConsent('') } })
  const view = target && !query.isFetching && !query.isError && !write.isError ? query.data : undefined
  const key = JSON.stringify([target, history.dataUpdatedAt, query.dataUpdatedAt, view?.preview_digest, view?.review?.review_id, reason, decision])
  const confirmed = !!view && consent === key, restoreConfirmed = !!view && restoreConsent === key
  const editable = !!view?.can_review && !write.isPending && !write.isError
  const canReview = editable && confirmed && !!reason.trim(), canRestore = editable && restoreConfirmed && view?.review?.decision === 'approve'
  const error = history.error || query.error || write.error
  const stale = error instanceof StalePublication || error instanceof ApiRequestError && error.status === 409
  const { onFailure } = scope
  useEffect(() => { if ((history.isError || query.isError) && !stale) onFailure(true) }, [history.isError, query.isError, stale, onFailure])
  function reset() { setConsent(''); setRestoreConsent(''); write.reset() }
  function submit(action: 'review' | 'publish') {
    if (!view || submitted.current || !(action === 'review' ? canReview : canRestore)) return
    submitted.current = true; setConsent(''); setRestoreConsent('')
    write.mutate({ view, action, attempt: crypto.randomUUID() })
  }
  return { open, baselineId, after, page, history, query, write, view, selectedId, reason, decision, confirmed, restoreConfirmed, canReview, canRestore, error, stale,
    toggle: () => { setOpen(!open); setSelectedId(''); reset() },
    baseline: (id: string) => { setBaselineId(id); setAfter(0); setSelectedId(''); reset() },
    choose: (id: string) => { setSelectedId(id); reset() },
    paginate: (value: number) => { setAfter(value); setSelectedId(''); reset() },
    reload: () => { setSelectedId(''); reset(); void history.refetch() },
    explain: (value: string) => { setReason(value); reset() }, decide: (value: 'approve' | 'reject') => { setDecision(value); reset() },
    confirm: (checked: boolean) => setConsent(checked ? key : ''), confirmRestore: (checked: boolean) => setRestoreConsent(checked ? key : ''), submit }
}
