import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { testDesignReviewApi } from './testDesignReviewApi'

export function useTestDesignReviewQueue(projectId: string, sessionId: string) {
  const [open, setOpen] = useState(false), [selected, setSelected] = useState(''), [blocked, setBlocked] = useState(false)
  const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
  const list = useInfiniteQuery({ ...sensitive, queryKey: ['test-design-review-drafts', projectId, sessionId], initialPageParam: '',
    queryFn: ({ pageParam, signal }) => testDesignReviewApi.page(projectId, pageParam, signal),
    getNextPageParam: (page) => page.next_after_id ?? undefined, enabled: open && !!sessionId && !blocked })
  const candidates = list.data?.pages.flatMap((page) => page.items)
  const overlap = !!candidates && new Set(candidates.map((item) => item.metadata.generation_id)).size !== candidates.length
  const rows = !blocked && !list.isError && !list.isFetching && !overlap ? candidates : undefined
  const item = rows?.find((value) => value.metadata.generation_id === selected)
  const detail = useQuery({ ...sensitive, queryKey: ['test-design-review-draft', projectId, sessionId, selected, item?.metadata.artifact_hash],
    queryFn: ({ signal }) => testDesignReviewApi.draft(projectId, item!, signal), enabled: open && !!sessionId && !!item && !blocked })
  const failed = blocked || overlap || list.isError || detail.isError
  return { open, list, detail, failed, selected, rows: failed ? undefined : rows,
    draft: !failed && item && !detail.isFetching ? detail.data : undefined,
    toggle: () => { setOpen(!open); setSelected(''); setBlocked(false) },
    choose: (id: string) => { setSelected(id); setBlocked(false) },
    onMappingFailure: () => { setBlocked(true); setSelected('') },
    reload: () => { setSelected(''); setBlocked(false); void list.refetch() },
    loadMore: () => { if (!failed && !list.isFetching && list.hasNextPage) void list.fetchNextPage() },
  }
}
