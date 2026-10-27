import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { mappingStagingApi } from './mappingStagingApi'
import type { GenerationArchive } from './types/testDesignGeneration'

export function useMappingStaging(draft: GenerationArchive, previous: string | null, scopeCurrent: boolean, sessionId: string, onFailure: () => void) {
  const [open, setOpen] = useState(false), [epoch, setEpoch] = useState(0), [sequence, setSequence] = useState(0)
  const [changed, setChanged] = useState(0), [partBusy, setPartBusy] = useState(false), [finalBusy, setFinalBusy] = useState(false)
  const query = useQuery({ queryKey: ['mapping-staging', draft.metadata.project_id, sessionId, draft.metadata, previous, scopeCurrent, epoch], enabled: open,
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => mappingStagingApi.open(draft, previous, scopeCurrent, signal) })
  useEffect(() => { if (query.isError) onFailure() }, [query.isError, onFailure])
  const workspace = !query.isFetching && !query.isError ? query.data : undefined
  return { open, workspace, sequence, changed, partBusy, finalBusy, query, setPartBusy, setFinalBusy,
    toggle: () => { if (!partBusy && !finalBusy) { setOpen(!open); setSequence(0); setChanged(changed + 1) } },
    reload: () => { if (!partBusy && !finalBusy) { setEpoch(epoch + 1); setSequence(0); setChanged(changed + 1) } },
    choose: (value: number) => { if (workspace && !partBusy && !finalBusy && Number.isInteger(value) && value >= 0 && value < workspace.plan.part_count) {
      setSequence(value); setChanged(changed + 1)
    } },
    invalidate: () => setChanged((v) => v + 1),
    close: () => setOpen(false),
  }
}
