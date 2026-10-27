import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { readFrozenImageSources } from '../system-image/frozenImageSources'
import type { ImageReadScope } from '../system-image/useImageRevisions'
import type { ImageRevisionSummary } from '../system-image/types/imageRevision'
import { nativeBuildApi } from './nativeBuildApi'
import { nativeRecovery } from './nativeBuildRecovery'
import { nativeArtifactPath, nativeSelectionKeys, requireNativeBuild } from './nativeBuildValidation'
import { generationDigest, generationEqual } from './testDesignGenerationValidation'
import type { NativeBuildAttempt, NativeBuildCommand, NativeBuildSelection } from './types/nativeBuilds'

const sensitive = { staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useNativeBuild(scope: ImageReadScope, revision: ImageRevisionSummary, actorId: string) {
  const client = useQueryClient(), live = useRef(true), submitted = useRef(false)
  const requireScope = () => requireNativeBuild(live.current && scope.projectId === revision.project_id)
  const [open, setOpen] = useState(false), [binding, setBinding] = useState(''), [path, setPath] = useState(''), [expected, setExpected] = useState('')
  const [consent, setConsent] = useState('')
  const [stored, setStored] = useState(() => {
    try { return { attempt: nativeRecovery.read(actorId, revision.project_id, revision.image_revision_id, revision.artifact_hash), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  })
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const prefix = ['native-builds', scope.projectId, actorId, scope.sessionId, revision.image_revision_id, revision.artifact_hash]
  const sources = useQuery({ ...sensitive, enabled: open, queryKey: [...prefix, 'sources'],
    queryFn: async ({ signal }) => { requireScope(); const value = await readFrozenImageSources(revision, signal); requireScope(); return value } })
  const fixed = !sources.isFetching && !sources.isError ? sources.data : undefined
  const code = fixed?.source_members.filter((s) => s.source_type === 'code' && s.status === 'captured') ?? []
  const selected = code.find((s) => s.binding_id === binding)
  const key = JSON.stringify([fixed, binding, path, expected, sources.dataUpdatedAt])
  const preview = useMutation({ retry: false, mutationFn: async (original?: NativeBuildCommand) => {
    requireNativeBuild(fixed)
    let selection: NativeBuildSelection
    if (original) selection = Object.fromEntries(nativeSelectionKeys.map((name) => [name, original[name]])) as unknown as NativeBuildSelection
    else {
      requireNativeBuild(selected && selected.source_revision_id)
      selection = { project_id: scope.projectId, image_revision_id: revision.image_revision_id,
        image_artifact_hash: revision.artifact_hash, binding_id: selected.binding_id, source_revision_id: selected.source_revision_id,
        artifact_path: path, expected_artifact_hash: expected || null }
    }
    const value = await nativeBuildApi.preview(selection, fixed, requireScope)
    requireNativeBuild(!original || generationEqual(value.request, original))
    return { key: original ? JSON.stringify(original) : key, sourceRead: sources.dataUpdatedAt, value }
  } })
  const prepared = fixed && !preview.isPending && !preview.isError && preview.data?.key === key ? preview.data : undefined
  const write = useMutation({ retry: false, mutationFn: async (value: { input: NativeBuildCommand } | { attempt: NativeBuildAttempt }) => {
    requireNativeBuild(fixed); requireScope()
    if ('attempt' in value) return nativeBuildApi.confirm(value.attempt, fixed, requireScope)
    const attempt = { projectId: scope.projectId, imageId: revision.image_revision_id, imageHash: revision.artifact_hash,
      requestKey: crypto.randomUUID(), requestHash: await canonicalDigest(value.input) }
    requireScope(); nativeRecovery.save(actorId, attempt); setStored({ attempt, invalid: false })
    return nativeBuildApi.prepare(value.input, attempt, fixed, (acknowledged) => {
      nativeRecovery.acknowledge(actorId, acknowledged)
      if (live.current) setStored({ attempt: acknowledged, invalid: false })
    }, requireScope)
  }, onSettled: () => { if (live.current) { setConsent(''); void client.invalidateQueries({ queryKey: [...prefix, 'original'] }) } } })
  const recovery = useQuery({ ...sensitive, enabled: open && !!fixed && !!stored.attempt && !write.isPending,
    queryKey: [...prefix, 'original', stored.attempt?.requestKey, sources.dataUpdatedAt], queryFn: async ({ signal }) => {
      requireNativeBuild(stored.attempt && fixed); requireScope()
      const value = await nativeBuildApi.recover(stored.attempt, fixed, signal), attempt = { ...stored.attempt, commandId: value.command.id }
      signal.throwIfAborted(); requireScope(); nativeRecovery.acknowledge(actorId, attempt)
      return { ...value, attempt }
    }, refetchInterval: (query) => ['pending', 'running'].includes(query.state.data?.command.status ?? '') ? 10000 : false })
  const original = fixed && !write.isPending && !recovery.isFetching && !recovery.isError ? recovery.data : undefined
  const originalPrepared = original && !preview.isPending && !preview.isError && preview.data?.sourceRead === sources.dataUpdatedAt
    && preview.data.key === JSON.stringify(original.input) ? preview.data : undefined
  const denied = (error: unknown) => error instanceof ApiRequestError && [403, 502].includes(error.status)
  const failed = open && (sources.isError || denied(recovery.error) || denied(preview.error) || denied(write.error))
  const { onFailure } = scope
  useEffect(() => { if (failed) onFailure(true) }, [failed, onFailure])
  const busy = sources.isFetching || preview.isPending || write.isPending || recovery.isFetching
  const editable = !!fixed && !stored.attempt && !stored.invalid && !failed && !busy
  const confirmationKey = JSON.stringify([prepared, originalPrepared, original?.input, original?.command.status, recovery.dataUpdatedAt, sources.dataUpdatedAt])
  const confirmed = consent === confirmationKey && !!(prepared || originalPrepared)
  const mayPreview = editable && !!selected && nativeArtifactPath(path) && (!expected || generationDigest(expected))
  const mayConfirmOriginal = !busy && !failed && !!fixed && !!originalPrepared && original?.command.status === 'waiting_confirmation' && confirmed
  const complete = original?.view?.metadata ? original.view : undefined
  const terminal = original && ['completed', 'failed', 'cancelled'].includes(original.command.status)
    && (complete || !original.view || original.view.metadata === null && !original.view.outcome_unknown && !original.view.call_reserved)
  return { open, code, binding, path, expected, preview, prepared, originalPrepared, stored, recovery, original, complete, confirmed, failed, busy, editable,
    sourceRead: sources.dataUpdatedAt,
    write, mayPreview, maySave: mayPreview && !!prepared && confirmed, mayConfirmOriginal, mayStartAnother: !!terminal && !busy && !failed,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    edit: (field: 'binding' | 'path' | 'expected', value: string) => { if (editable) {
      if (field === 'binding') setBinding(value)
      if (field === 'path') setPath(value)
      if (field === 'expected') setExpected(value)
      setConsent(''); preview.reset()
    } },
    verify: () => { if (mayPreview) { setConsent(''); preview.mutate(undefined) } },
    verifyOriginal: () => { if (!busy && !failed && original?.command.status === 'waiting_confirmation') { setConsent(''); preview.mutate(original.input) } },
    confirm: (checked: boolean) => setConsent(checked ? confirmationKey : ''),
    save: () => { if (prepared && mayPreview && confirmed && !submitted.current) {
      submitted.current = true; setConsent(''); write.mutate({ input: prepared.value.request })
    } },
    confirmOriginal: () => { if (mayConfirmOriginal && original && !submitted.current) {
      submitted.current = true; setConsent(''); write.mutate({ attempt: original.attempt })
    } },
    reload: () => { if (!busy) {
      setConsent(''); preview.reset(); submitted.current = false
      try { setStored({ attempt: nativeRecovery.read(actorId, revision.project_id, revision.image_revision_id, revision.artifact_hash), invalid: false }) }
      catch { setStored({ attempt: null, invalid: true }) }
      void sources.refetch(); if (stored.attempt) void recovery.refetch()
    } },
    another: () => { if (terminal && original && !busy && !failed) {
      nativeRecovery.clear(actorId, original.attempt); setStored({ attempt: null, invalid: false })
      setBinding(''); setPath(''); setExpected(''); setConsent(''); submitted.current = false; preview.reset(); write.reset()
    } },
  }
}
