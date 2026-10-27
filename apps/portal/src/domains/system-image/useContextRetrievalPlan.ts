import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { readContextRetrievalPlan } from './contextRetrievalPlanApi'
import type { IndexGeneration } from './types/frozenIndex'

export function useContextRetrievalPlan(generation: IndexGeneration) {
  const session = useId(), [open, setOpen] = useState(false)
  const preview = useQuery({ enabled: open, gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryKey: ['context-retrieval-plan', generation.project_id, generation.generation_id, generation.artifact_hash, session],
    queryFn: ({ signal }) => readContextRetrievalPlan(generation, signal),
  })
  return { preview, open, view: open && !preview.isFetching && !preview.isError ? preview.data : undefined,
    inspect: () => { if (!preview.isFetching) { setOpen(true); if (open) void preview.refetch() } },
  }
}
