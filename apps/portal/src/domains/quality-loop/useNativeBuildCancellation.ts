import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import type { ImageReadScope } from '../system-image/useImageRevisions'
import { createNativeRecovery } from './nativeBuildRecovery'
import { nativeBuildCancellationApi } from './nativeBuildCancellationApi'
import { requireNativeBuild } from './nativeBuildValidation'
import type { NativeBuildAttempt, NativeBuildCommand } from './types/nativeBuilds'

export function useNativeBuildCancellation(scope: ImageReadScope, actorId: string, targetId: string,
  input: NativeBuildCommand, targetStatus: string, sourceRead: number, reloadTarget: () => void) {
  const [storage] = useState(() => createNativeRecovery(() => window.sessionStorage, 'nasus.native-build-cancel.v1:' + targetId))
  const live = useRef(true), submitted = useRef(false), [consent, setConsent] = useState('')
  const [submittedOnce, setSubmittedOnce] = useState(false)
  const readPointer = () => {
    try { return { attempt: storage.read(actorId, input.project_id, input.image_revision_id, input.image_artifact_hash), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  }
  const [stored, setStored] = useState(readPointer)
  const requireScope = () => requireNativeBuild(live.current && scope.projectId === input.project_id)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const write = useMutation({ retry: false, mutationFn: async (original?: NativeBuildAttempt) => {
    requireScope()
    if (original) return nativeBuildCancellationApi.confirm(original, targetId, requireScope)
    const attempt = { projectId: input.project_id, imageId: input.image_revision_id, imageHash: input.image_artifact_hash,
      requestKey: crypto.randomUUID(), requestHash: await canonicalDigest({ project_id: input.project_id, invocation_id: targetId }) }
    requireScope(); storage.save(actorId, attempt); setStored({ attempt, invalid: false })
    return nativeBuildCancellationApi.create(attempt, targetId, (value) => {
      storage.acknowledge(actorId, value)
      if (live.current) setStored({ attempt: value, invalid: false })
    }, requireScope)
  }, onSettled: () => { if (live.current) { setConsent(''); void recovery.refetch(); reloadTarget() } } })
  const recovery = useQuery({ queryKey: ['native-build-cancellation', actorId, scope.sessionId, input.project_id, targetId,
    input.image_revision_id, input.image_artifact_hash, stored.attempt?.requestKey, sourceRead],
    enabled: !!stored.attempt && !write.isPending, staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: async ({ signal }) => {
      requireNativeBuild(stored.attempt); requireScope()
      const value = await nativeBuildCancellationApi.recover(stored.attempt, targetId, signal)
      signal.throwIfAborted(); requireScope()
      const attempt = { ...stored.attempt, commandId: value.command.id }; storage.acknowledge(actorId, attempt)
      return { ...value, attempt }
    }, refetchInterval: (query) => ['pending', 'running'].includes(query.state.data?.command.status ?? '') ? 10000 : false })
  const denied = [recovery.error, write.error].some((error) => error instanceof ApiRequestError && [403, 502].includes(error.status))
  const { onFailure } = scope
  useEffect(() => { if (denied) onFailure(true) }, [denied, onFailure])
  const busy = write.isPending || recovery.isFetching, original = !busy && !recovery.isError ? recovery.data : undefined
  const active = ['pending', 'running'].includes(targetStatus), key = JSON.stringify([targetId, input, targetStatus, sourceRead, original?.command.id, recovery.dataUpdatedAt])
  const checked = consent === key, error = stored.invalid || recovery.isError || write.isError && !original
  const eligible = active && !busy && !error && !denied && !submittedOnce && (!stored.attempt || original?.command.status === 'waiting_confirmation')
  const mayPrepareAnother = active && !busy && !error && !denied && !!original
    && ['failed', 'cancelled'].includes(original.command.status)
  return { visible: active || !!stored.attempt || stored.invalid, checked, busy, error, original, eligible, mayPrepareAnother,
    check: (value: boolean) => { if (eligible) setConsent(value ? key : '') },
    cancel: () => { if (eligible && checked && !submitted.current) { submitted.current = true; setSubmittedOnce(true); setConsent(''); write.mutate(original?.attempt) } },
    reload: () => { if (!busy) { setConsent(''); submitted.current = false; setSubmittedOnce(false); setStored(readPointer()); if (stored.attempt) void recovery.refetch() } },
    prepareAnother: () => { if (mayPrepareAnother && original) {
      storage.clear(actorId, original.attempt); setStored({ attempt: null, invalid: false })
      setConsent(''); submitted.current = false; setSubmittedOnce(false); write.reset()
    } },
  }
}
