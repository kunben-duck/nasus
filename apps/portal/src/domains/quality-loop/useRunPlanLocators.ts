import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { readRunPlanLocators } from './runPlanLocatorApi'
import type { RunPlanArchive } from './types/runPlans'

export function useRunPlanLocators(plan: RunPlanArchive, actorId: string, onFailure: () => void) {
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['run-plan-locators', actorId, plan.metadata.project_id, plan.metadata.run_plan_id, plan.metadata.artifact_hash],
    queryFn: ({ signal }) => readRunPlanLocators(plan, signal), enabled: open, retry: false, staleTime: 0, gcTime: 0,
    refetchOnWindowFocus: 'always' })
  useEffect(() => { if (query.isError) onFailure() }, [query.isError, onFailure])
  return { open, busy: query.isFetching, failed: query.isError,
    value: open && !query.isFetching && !query.isError ? query.data : undefined,
    toggle: () => setOpen(!open), reload: () => { if (open && !query.isFetching) void query.refetch() } }
}
