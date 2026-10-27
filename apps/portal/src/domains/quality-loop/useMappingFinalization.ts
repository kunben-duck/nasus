import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { mappingStagingApi } from './mappingStagingApi'
import { mappingQuery, mappingReason } from './mappingStagingValidation'
import type { MappingFinalize } from './types/testDesignMapping'
import type { MappingWorkspace } from './types/mappingStaging'

export function useMappingFinalization(workspace: MappingWorkspace, savedEpoch: number, onFailure: () => void, onDone: () => void) {
  const [reason, setReason] = useState(''), [consent, setConsent] = useState(''), [open, setOpen] = useState(false), submitted = useRef(false)
  const query = useQuery({ queryKey: ['mapping-final-preview', workspace.plan.generation_pin.project_id, workspace.actorId, workspace.plan.plan_digest, savedEpoch],
    enabled: open, gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => mappingStagingApi.preview(workspace, signal) })
  useEffect(() => { if (query.isError) onFailure() }, [query.isError, onFailure])
  const write = useMutation({ retry: false, mutationFn: ({ input, attempt }: { input: MappingFinalize; attempt: string }) => mappingStagingApi.record(input, attempt),
    onSuccess: onDone, onSettled: () => { setConsent(''); void query.refetch() } })
  const view = !query.isFetching && !query.isError ? query.data : undefined, busy = query.isFetching || write.isPending
  const key = JSON.stringify([workspace.plan.plan_digest, savedEpoch, query.dataUpdatedAt, view, reason])
  const confirmed = key === consent, canSubmit = !!view?.ready_for_confirmation && !!view.part_set && confirmed && mappingReason(reason) && !busy && write.isIdle
  return { open, view, busy, write, reason, confirmed, canSubmit,
    inspect: () => { if (!write.isPending) { submitted.current = false; write.reset(); setConsent(''); setOpen(true); void query.refetch() } },
    explain: (text: string) => { setConsent(''); setReason(text) }, confirm: (checked: boolean) => setConsent(checked ? key : ''),
    submit: () => { if (canSubmit && view?.part_set && !submitted.current) {
      submitted.current = true; setConsent(''); write.mutate({ attempt: crypto.randomUUID(), input: { ...mappingQuery(workspace),
        plan_digest: workspace.plan.plan_digest, expected_previous_revision_id: workspace.plan.expected_previous_revision_id,
        part_set_digest: view.part_set.part_set_digest, decision: 'review', reason, policy_revision: 'nasus.test-design-mapping.v2' } })
    } },
  }
}
