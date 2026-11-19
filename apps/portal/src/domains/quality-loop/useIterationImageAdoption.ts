import { useRef, useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from '../../shared/api/client'
import { imageRevisionApi } from '../system-image/imageRevisionApi'
import { requirementReviewsApi } from './requirementReviews'
import type { VersionDelivery } from './types/delivery'
import { verifyImageAdoption, type IterationImageOption } from './iterationImageAdoption'

export function useIterationImageAdoption(view: VersionDelivery, actorId: string) {
  const client = useQueryClient(), processing = useRef(false)
  const [open, setOpen] = useState(false), [selected, setSelected] = useState(''), [reason, setReason] = useState('')
  const [consent, setConsent] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(false)
  const key = ['iteration-image-adoption', view.project_id, view.version_id, actorId, view.iteration_image?.image_revision_id]
  const history = useInfiniteQuery({ queryKey: [...key, 'history'], enabled: open, initialPageParam: '',
    gcTime: 0, retry: false, queryFn: ({ pageParam, signal }) => imageRevisionApi.list(view.project_id, pageParam, signal),
    getNextPageParam: (page) => page.next_after_id ?? undefined })
  const option = useQuery({ queryKey: [...key, 'option', selected], enabled: open && !!selected,
    gcTime: 0, staleTime: 0, retry: false, queryFn: async ({ signal }) => {
      const value = await request<IterationImageOption>(`/v1/projects/${encodeURIComponent(view.project_id)}/versions/${encodeURIComponent(view.version_id)}/delivery/image-options/${encodeURIComponent(selected)}`, { signal, cache: 'no-store' })
      return verifyImageAdoption(value, view, selected)
    } })
  const preview = !option.isFetching && !option.isError ? option.data : undefined
  const input = preview ? { ...preview.request, reason: reason.trim() } : null
  const consentKey = JSON.stringify([input, option.dataUpdatedAt])
  const confirmed = !!input && !!reason.trim() && consent === consentKey
  async function adopt() {
    if (processing.current || !confirmed || !input) return
    processing.current = true; setBusy(true); setError(false)
    try {
      await requirementReviewsApi.execute(actorId, 'quality.iteration_image.adopt', input)
      await client.invalidateQueries({ queryKey: ['version-delivery', view.project_id] })
      await client.invalidateQueries({ queryKey: ['version-requirements', view.project_id] })
      await client.invalidateQueries({ queryKey: ['requirement-review'] })
      setOpen(false); setSelected(''); setReason('')
    } catch { setError(true) }
    finally { processing.current = false; setBusy(false); setConsent('') }
  }
  return { open, setOpen, selected, setSelected, reason, setReason, busy, error, history, option, preview, confirmed,
    confirm: (value: boolean) => setConsent(value ? consentKey : ''), adopt }
}
