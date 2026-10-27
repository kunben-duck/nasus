import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { fixtureHistoryApi } from './httpFixtureHistoryApi'
import { verifyFixtureHistoryPages } from './httpFixtureHistoryValidation'
import { fixtureObservationApi } from './httpFixtureObservationApi'
import { generationEqual } from './testDesignGenerationValidation'

export function useHttpFixtureHistory(projectId: string, actorId: string) {
  const [open, setOpen] = useState(false), [selected, setSelected] = useState(''), [inspect, setInspect] = useState(false)
  const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
  const list = useInfiniteQuery({ ...sensitive, queryKey: ['fixture-operation-history', projectId, actorId], initialPageParam: '',
    queryFn: ({ pageParam, signal }) => fixtureHistoryApi.page(projectId, pageParam, signal),
    getNextPageParam: (page) => page.next_after_id ?? undefined, enabled: open && !!actorId })
  let rows: ReturnType<typeof verifyFixtureHistoryPages> | undefined, invalid = false
  if (open && actorId && !list.isError && !list.isFetching && list.data) {
    try { rows = verifyFixtureHistoryPages(list.data.pages, projectId) } catch { invalid = true }
  }
  const item = rows?.find((value) => value.invocation_id === selected)
  const detail = useQuery({ ...sensitive, queryKey: ['fixture-operation-metadata', projectId, actorId, selected, item?.request_digest],
    queryFn: ({ signal }) => fixtureHistoryApi.read(projectId, item!, signal), enabled: open && !!actorId && !!item })
  const metadata = item && !detail.isFetching && generationEqual(detail.data, item) ? detail.data : undefined
  const scope = rows && list.data?.pages[0].source_scope_digest
  const journal = useQuery({ ...sensitive, queryKey: ['fixture-original-observation', projectId, actorId, selected,
    metadata?.request_digest, metadata?.status, scope],
    queryFn: ({ signal }) => fixtureObservationApi.read(metadata!, scope!, signal),
    enabled: open && !!actorId && inspect && !!metadata && !!scope && !detail.isError })
  const journalFailed = inspect && !!metadata && journal.isError
  const failed = list.isError || invalid || detail.isError || journalFailed
  const reading = inspect && journal.isFetching
  return { open, list, detail, journal, inspect, selected, failed, rows: failed || reading ? undefined : rows,
    metadata: !failed && !reading ? metadata : undefined,
    observation: !failed && !reading && inspect && metadata && scope && actorId
      && generationEqual(journal.data?.selected, metadata) && journal.data?.source_scope_digest === scope ? journal.data : undefined,
    inspectJournal: () => setInspect(true),
    toggle: () => { setOpen(!open); setSelected(''); setInspect(false) },
    choose: (id: string) => { setSelected(id); setInspect(false) },
    reload: () => { setSelected(''); setInspect(false); void list.refetch() },
    loadMore: () => { if (!failed && !list.isFetching && list.hasNextPage) void list.fetchNextPage() },
  }
}
