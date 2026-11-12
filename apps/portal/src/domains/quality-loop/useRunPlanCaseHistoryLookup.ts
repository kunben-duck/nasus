import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { caseExecutionApi } from './runPlanCaseApi'
import { caseId } from './runPlanCaseValidation'
import type { RunPlanArchive } from './types/runPlans'

export function useRunPlanCaseHistoryLookup(scope: RunPlanArchive | string, actorId: string) {
  const [draft, setDraft] = useState(''), [selected, setSelected] = useState('')
  const metadata = typeof scope !== 'string' ? scope.metadata : undefined
  const projectId = typeof scope === 'string' ? scope : scope.metadata.project_id
  const commandId = draft.trim(), enabled = caseId(selected) && selected === commandId
  const lookup = useQuery({ queryKey: ['run-plan-case-history-lookup', actorId, projectId,
    metadata?.run_plan_id, metadata?.artifact_hash, selected],
    enabled, retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => caseExecutionApi.readHistoryByCommand(scope, selected, signal) })
  return { draft, canRead: caseId(commandId) && !lookup.isFetching, busy: lookup.isFetching,
    failed: enabled && !lookup.isFetching && lookup.isError,
    original: enabled && !lookup.isFetching && !lookup.isError ? lookup.data : undefined,
    edit: (value: string) => { setDraft(value); setSelected('') },
    read: () => {
      if (!caseId(commandId) || lookup.isFetching) return
      if (enabled) void lookup.refetch()
      else setSelected(commandId)
    },
  }
}
