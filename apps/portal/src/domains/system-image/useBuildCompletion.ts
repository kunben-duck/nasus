import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { buildCompletionApi, parseCompletionPointer } from './buildCompletionApi'
import type { BuildReviewHandoff } from './buildReviewHandoff'
import type { BuildCompletionPointer } from './types/buildCompletion'

export function useBuildCompletion(review: BuildReviewHandoff, sessionId: string) {
  const [params, setParams] = useSearchParams()
  const [sending, setSending] = useState(false), [unacknowledged, setUnacknowledged] = useState(false)
  const inFlight = useRef(false), mounted = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  let pointer: BuildCompletionPointer | null = null, invalid = false
  try { pointer = parseCompletionPointer(params) } catch { invalid = true }
  const observed = useQuery({
    queryKey: ['build-completion', review.projectId, review.selection.goalId, review.investigation.revision_hash,
      sessionId, pointer?.requestKey, pointer?.invocationId],
    enabled: Boolean(pointer) && !invalid && !sending, retry: false, staleTime: 0, gcTime: 0,
    refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => buildCompletionApi.read(review, pointer!, signal),
    refetchInterval: (query) => !query.state.error && ['pending', 'running'].includes(query.state.data?.command.status ?? '') ? 1000 : false,
  })
  const remember = (value: BuildCompletionPointer) => setParams((current) => {
    const next = new URLSearchParams(current)
    next.set('build_completion_request', value.requestKey)
    if (value.invocationId) next.set('build_completion_invocation', value.invocationId)
    else next.delete('build_completion_invocation')
    return next
  }, { replace: true })
  useEffect(() => {
    if (pointer && !pointer.invocationId && observed.data && !observed.isError && !observed.isFetching) {
      remember({ ...pointer, invocationId: observed.data.command.id })
    }
  })
  async function assess() {
    if (inFlight.current || pointer || invalid) return
    inFlight.current = true; setSending(true); setUnacknowledged(false)
    const original = { requestKey: crypto.randomUUID(), invocationId: null }
    remember(original)
    try {
      const command = await buildCompletionApi.prepare(review, original)
      if (mounted.current) remember({ ...original, invocationId: command.id })
    } catch { if (mounted.current) setUnacknowledged(true) }
    finally { inFlight.current = false; if (mounted.current) setSending(false) }
  }
  const inaccessible = invalid || observed.isError
  return { started: Boolean(pointer), sending, checking: observed.isFetching,
    inaccessible, unacknowledged: unacknowledged && !observed.data,
    observation: inaccessible || observed.isFetching || sending ? null : observed.data ?? null,
    assess, reload: () => { if (invalid || !pointer) return; setUnacknowledged(false); void observed.refetch() } }
}
