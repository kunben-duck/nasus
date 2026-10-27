import { useId, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { contextRetrievalApi } from './contextRetrievalApi'
import type { ContextRetrievalPlan } from './types/contextRetrievalPlan'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useContextRetrieval(plan: ContextRetrievalPlan) {
  const session = useId(), [consent, setConsent] = useState(false), submitted = useRef(false)
  const history = useQuery({ ...sensitive, queryKey: ['context-retrieval-history', plan.request, plan.plan_digest, session],
    queryFn: ({ signal }) => contextRetrievalApi.latest(plan, signal), refetchInterval: 2000 })
  const job = !history.isError ? history.data : undefined
  const active = job?.status === 'running' || job?.status === 'pending'
  const result = useQuery({ ...sensitive, enabled: job?.status === 'completed',
    queryKey: ['context-retrieval-result', plan.request, plan.plan_digest, job?.id, session],
    queryFn: ({ signal }) => contextRetrievalApi.result(plan, job!.id, signal) })
  const write = useMutation({ retry: false, mutationFn: () => contextRetrievalApi.start(plan, crypto.randomUUID()),
    onSettled: () => { setConsent(false); void history.refetch() } })
  const cancel = useMutation({ retry: false, mutationFn: () => contextRetrievalApi.cancel(plan.request.project_id, job!.id),
    onSettled: () => { void history.refetch() } })
  const busy = write.isPending || cancel.isPending || !!active
  const ready = !history.isFetching && !history.isError && !busy && write.isIdle && consent && plan.execution_available
  const view = job?.status === 'completed' && !result.isFetching && !result.isError && !history.isError ? result.data : undefined
  return { history, job, result, view, write, cancel, busy, ready, consent, setConsent,
    start: () => { if (ready && !submitted.current) { submitted.current = true; write.mutate() } },
    stop: () => { if (active && !cancel.isPending) cancel.mutate() },
  }
}
