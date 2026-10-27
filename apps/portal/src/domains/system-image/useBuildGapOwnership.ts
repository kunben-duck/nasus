import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { assignmentInput, buildGapOwnershipApi, parseGapAssignmentPointer } from './buildGapOwnershipApi'
import type { BuildReviewHandoff } from './buildReviewHandoff'
import type { BuildCompletionObservation, BuildCompletionPointer } from './types/buildCompletion'
import type { GapAssignment } from './types/buildGapOwnership'

export function useBuildGapOwnership(review: BuildReviewHandoff, completion: BuildCompletionObservation, sessionId: string) {
  const [params, setParams] = useSearchParams()
  const client = useQueryClient()
  const [editing, setEditing] = useState(false), [assignments, setAssignments] = useState<GapAssignment[]>([])
  const [sending, setSending] = useState(false), [uncertain, setUncertain] = useState(false)
  const inFlight = useRef(false), mounted = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  let pointer: BuildCompletionPointer | null = null, invalid = false
  try { pointer = parseGapAssignmentPointer(params) } catch { invalid = true }
  const scope = ['build-gap-ownership', review.projectId, completion.command.id, sessionId]
  const observationKey = (value: BuildCompletionPointer | null) => [...scope, value?.requestKey, value?.invocationId]
  // The report and command form one verified observation. A fresh write
  // acknowledgement can seed it; remounts and focus still reauthorize reads.
  const observed = useQuery({ queryKey: observationKey(pointer), retry: false, staleTime: Infinity, gcTime: 0,
    refetchOnMount: false, enabled: !invalid && !sending && !uncertain,
    refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => buildGapOwnershipApi.observe(review, completion, pointer, signal),
    refetchInterval: (query) => !query.state.error && ['pending', 'running'].includes(query.state.data?.command?.status ?? '') ? 1000 : false })
  const ownersQuery = useQuery({ queryKey: [...scope, 'owners'], enabled: editing && !sending,
    retry: false, staleTime: 0, gcTime: 0, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => buildGapOwnershipApi.owners(review, completion, signal) })
  const remember = (value: BuildCompletionPointer | null) => setParams((current) => {
    const next = new URLSearchParams(current)
    if (value) {
      next.set('build_gap_assignment_request', value.requestKey)
      if (value.invocationId) next.set('build_gap_assignment_invocation', value.invocationId)
      else next.delete('build_gap_assignment_invocation')
    } else { next.delete('build_gap_assignment_request'); next.delete('build_gap_assignment_invocation') }
    return next
  }, { replace: true })
  useEffect(() => {
    if (pointer && !pointer.invocationId && observed.data?.command && !observed.isFetching && !observed.isError) {
      const resolved = { ...pointer, invocationId: observed.data.command.id }
      client.setQueryData(observationKey(resolved), observed.data)
      remember(resolved)
    }
  })
  const checking = observed.isFetching
  const inaccessible = invalid || observed.isError
  const view = inaccessible || checking || sending || uncertain ? null : observed.data?.view ?? null
  const command = inaccessible || checking || sending || uncertain ? null : observed.data?.command ?? null
  function edit() {
    if (!view || inFlight.current || command && ['waiting_confirmation', 'pending', 'running'].includes(command.status)) return
    remember(null); setUncertain(false)
    const latest = view.history.at(-1)
    setAssignments(view.gaps.map((gap) => ({ gap_id: gap.gap_id, owner_actor_id: gap.owner_actor_id ?? '',
      reason: latest?.assignments.find((item) => item.gap_id === gap.gap_id)?.reason ?? '' })))
    setEditing(true)
  }
  async function send(confirming: boolean) {
    if (inFlight.current || !view || confirming && (!pointer || command?.status !== 'waiting_confirmation')
        || !confirming && pointer) return
    inFlight.current = true; setSending(true); setUncertain(false)
    const original = pointer ?? { requestKey: crypto.randomUUID(), invocationId: null }
    if (!confirming) { remember(original); setEditing(false) }
    try {
      const result = confirming ? await buildGapOwnershipApi.confirm(review, completion, original)
        : await buildGapOwnershipApi.prepare(review, completion, assignmentInput(review, completion, view, assignments), original)
      if (mounted.current) {
        const resolved = { ...original, invocationId: result.command.id }
        client.setQueryData(observationKey(resolved), result)
        remember(resolved)
      }
    } catch { if (mounted.current) setUncertain(true) }
    finally { inFlight.current = false; if (mounted.current) setSending(false) }
  }
  const owners = ownersQuery.isFetching || ownersQuery.isError ? null : ownersQuery.data ?? null
  return { view, command, editing, assignments, setAssignments, owners,
    ownersUnavailable: ownersQuery.isError, checking, sending, inaccessible, uncertain,
    edit, cancelEdit: () => setEditing(false), prepare: () => send(false), confirm: () => send(true),
    reload: () => { if (invalid || sending) return; setUncertain(false); void observed.refetch() } }
}
