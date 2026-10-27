import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ToolInvocation } from '../platform/types/tool'
import { structureCancellationApi } from './structureCancellationApi'
import type { StructureCommandPin } from './structureBuildApi'
import type { ImageReadScope } from './useImageRevisions'

export function useStructureCancellation(scope: ImageReadScope, input: StructureCommandPin | null, command: ToolInvocation | null | undefined) {
  const client = useQueryClient()
  const enabled = Boolean(input && command && !['completed', 'failed', 'cancelled'].includes(command.status))
  const pin = input && command ? { project_id: input.project_id, original_invocation_id: command.id,
    plan_id: input.plan_id, plan_digest: input.plan_digest, target_baseline_id: input.target_baseline_id } : null
  const identity = JSON.stringify([scope.sessionId, pin])
  const query = useQuery({ queryKey: ['system-image', scope.projectId, 'structure-stop', identity], enabled,
    staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => structureCancellationApi.status(pin!, signal),
    refetchInterval: (value) => enabled && !value.state.error ? 1000 : false,
  })
  const [checked, setChecked] = useState('')
  const [writing, setWriting] = useState(false)
  const [failed, setFailed] = useState('')
  const active = useRef(false)
  const attempt = useRef<{ identity: string; key: string } | null>(null)
  // Keep controls mounted during revalidation, but never accept stale consent.
  const view = enabled && !query.isError ? query.data : undefined
  const consent = view ? JSON.stringify([identity, view]) : ''
  const approved = Boolean(consent && checked === consent)
  const error = enabled && (query.isError || failed === identity)
  async function cancel() {
    if (active.current || query.isFetching || !view?.can_cancel || !approved || error) return
    active.current = true; setWriting(true)
    if (!attempt.current || attempt.current.identity !== identity) attempt.current = { identity, key: crypto.randomUUID() }
    try {
      await structureCancellationApi.cancel(view, attempt.current.key)
      setChecked('')
      await client.invalidateQueries({ queryKey: ['system-image', scope.projectId, 'structure-command'] })
      await client.invalidateQueries({ queryKey: ['system-image', scope.projectId, 'structure-discovery'] })
      await query.refetch()
    } catch {
      setFailed(identity); setChecked('')
      // A lost acknowledgement may already have stopped a waiting command.
      // Only re-read its lifecycle; never replay the mutation automatically.
      void client.invalidateQueries({ queryKey: ['system-image', scope.projectId, 'structure-command'] })
      void client.invalidateQueries({ queryKey: ['system-image', scope.projectId, 'structure-discovery'] })
    }
    finally { active.current = false; setWriting(false) }
  }
  async function reload() {
    setChecked('')
    const result = await query.refetch()
    if (!result.isError) setFailed('')
  }
  return { visible: enabled && Boolean(view?.can_cancel || view?.cancellation_requested || error),
    requested: Boolean(view?.cancellation_requested), canCancel: Boolean(view?.can_cancel && approved && !error && !writing && !query.isFetching),
    checked: approved, check: (value: boolean) => { if (!query.isFetching && !writing && !error) setChecked(value ? consent : '') },
    busy: writing, error, checking: query.isFetching, cancel, reload }
}
