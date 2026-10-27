import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ownedBuildCompletionApi, parseOwnedCompletionPointer } from './ownedBuildCompletionApi'
import type { BuildReviewHandoff } from './buildReviewHandoff'
import type { BuildCompletionObservation, BuildCompletionPointer } from './types/buildCompletion'
import type { GapOwnershipView } from './types/buildGapOwnership'

export function useOwnedBuildCompletion(review: BuildReviewHandoff, completion: BuildCompletionObservation,
  view: GapOwnershipView, sessionId: string) {
  const [params, setParams] = useSearchParams()
  const [sending, setSending] = useState(false), [uncertain, setUncertain] = useState(false)
  const inFlight = useRef(false), mounted = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  let pointer: BuildCompletionPointer | null = null, invalid = false
  try { pointer = parseOwnedCompletionPointer(params) } catch { invalid = true }
  const observed = useQuery({ queryKey: ['owned-build-completion', review.projectId, completion.command.id,
    sessionId, pointer?.requestKey, pointer?.invocationId],
    enabled: Boolean(pointer) && !invalid && !sending && !uncertain, retry: false, staleTime: Infinity, gcTime: 0,
    refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => ownedBuildCompletionApi.read(review, completion, pointer!, signal),
    refetchInterval: (query) => !query.state.error && ['pending', 'running'].includes(query.state.data?.command.status ?? '') ? 1000 : false,
  })
  const remember = (value: BuildCompletionPointer) => setParams((current) => {
    const next = new URLSearchParams(current)
    next.set('build_owned_completion_request', value.requestKey)
    if (value.invocationId) next.set('build_owned_completion_invocation', value.invocationId)
    else next.delete('build_owned_completion_invocation')
    return next
  }, { replace: true })
  useEffect(() => {
    if (pointer && !pointer.invocationId && observed.data && !observed.isError && !observed.isFetching && !uncertain) {
      remember({ ...pointer, invocationId: observed.data.command.id })
    }
  })
  async function assess() {
    if (inFlight.current || pointer || invalid || view.gaps.some((gap) => gap.ownership_status !== 'confirmed')) return
    inFlight.current = true; setSending(true); setUncertain(false)
    const original = { requestKey: crypto.randomUUID(), invocationId: null }
    remember(original)
    try {
      const command = await ownedBuildCompletionApi.prepare(review, completion, view, original)
      if (mounted.current) remember({ ...original, invocationId: command.id })
    } catch { if (mounted.current) setUncertain(true) }
    finally { inFlight.current = false; if (mounted.current) setSending(false) }
  }
  return { started: Boolean(pointer), busy: sending || observed.isFetching,
    unavailable: invalid || uncertain || observed.isError,
    observation: invalid || uncertain || observed.isError || observed.isFetching || sending ? null : observed.data ?? null,
    assess, reload: () => { if (invalid || !pointer) return; setUncertain(false); void observed.refetch() } }
}
