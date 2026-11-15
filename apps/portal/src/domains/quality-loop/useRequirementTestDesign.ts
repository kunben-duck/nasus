import { useRef, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { requirementReviewsApi } from './requirementReviews'
import { contextPackApi } from '../system-image/contextPackApi'
import type { ContextRequest } from '../system-image/types/contextPack'

const sensitive = { retry: false, gcTime: 0, staleTime: 0 }

export function useRequirementTestDesign(selection: ContextRequest, actorId: string) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(false)
  const [selected, setSelected] = useState(''), [failed, setFailed] = useState(false)
  const processing = useRef(false)
  const key = ['iteration-test-design', actorId, selection.project_id, selection.iteration]
  const preview = useQuery({ ...sensitive, enabled: open, queryKey: [...key, 'preview'],
    queryFn: ({ signal }) => contextPackApi.preview(selection, signal) })
  const history = useInfiniteQuery({ ...sensitive, enabled: open, queryKey: [...key, 'history'], initialPageParam: '',
    queryFn: ({ pageParam, signal }) => contextPackApi.history(selection, pageParam, signal),
    getNextPageParam: (page) => page.next_after_id ?? undefined })
  const archive = useQuery({ ...sensitive, enabled: open && !!selected && !preview.isError, queryKey: [...key, 'archive', selected],
    queryFn: async ({ signal }) => {
      const value = await contextPackApi.read(selection, selected, signal), pin = value.context.iteration_pin
      if (!pin || Object.entries(selection.iteration!).some(([field, expected]) => pin[field as keyof typeof pin] !== expected))
        throw new Error('This context belongs to a different requirement confirmation')
      return value
    } })
  const rows = !history.isError && !history.isFetching ? history.data?.pages.flatMap((page) => page.items)
    .filter((item) => item.policy_revision === 'nasus.test-design-context.v6') : undefined
  const content = !failed && !preview.isError && !preview.isFetching && !archive.isError && !archive.isFetching ? archive.data : undefined
  async function compile() {
    if (processing.current || !preview.data || preview.isFetching || preview.isError) return
    processing.current = true; setBusy(true); setError(false)
    try {
      const value = preview.data
      const done = await requirementReviewsApi.execute(actorId, 'system_image.context.compile', {
        ...value.request, expected_input_digest: value.input_digest })
      const id = done.result?.object_refs.find((ref) => ref.startsWith('context_pack:'))?.slice(13)
      if (!id) throw new Error('No context receipt was returned')
      setFailed(false); setSelected(id); await history.refetch()
    } catch { setError(true) }
    finally { processing.current = false; setBusy(false) }
  }
  return { open, busy, error, selected, failed, preview, history, archive, rows, content, compile, setFailed,
    toggle: () => { if (!busy) setOpen(!open) },
    choose: (id: string) => { setFailed(false); setSelected(id) },
    reload: () => { if (!busy) { setFailed(false); void preview.refetch(); void history.refetch(); if (selected) void archive.refetch() } },
  }
}
