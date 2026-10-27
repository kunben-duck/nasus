import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiRequestError } from '../../shared/api/client'
import { contextPackApi, StaleContextPreview } from './contextPackApi'
import type { ContextPreview, ContextRequest, ContextSelection } from './types/contextPack'
import type { ImageReadScope } from './useImageRevisions'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useContextPacks(scope: ImageReadScope, selection: ContextSelection, publicationId?: string, retrievalBindings?: Record<string, string>) {
  const { onFailure } = scope
  const client = useQueryClient(), submitted = useRef(false)
  const [open, setOpen] = useState(false), [budget, setBudget] = useState('12000')
  const [requested, setRequested] = useState<ContextRequest | null>(null), [generation, setGeneration] = useState(0)
  const [consent, setConsent] = useState(''), [selected, setSelected] = useState(''), [cursors, setCursors] = useState([''])
  const prefix = ['context-packs', scope.projectId, scope.sessionId, selection.image_revision_id, selection.image_artifact_hash, publicationId]
  const history = useQuery({ ...sensitive, queryKey: [...prefix, 'history', cursors.at(-1)], enabled: open,
    queryFn: ({ signal }) => contextPackApi.history(selection, cursors.at(-1)!, signal) })
  const preview = useQuery({ ...sensitive, queryKey: [...prefix, 'preview', requested, generation], enabled: open && !!requested,
    queryFn: ({ signal }) => contextPackApi.preview(requested!, signal) })
  const archive = useQuery({ ...sensitive, queryKey: [...prefix, 'archive', selected], enabled: open && !!selected,
    queryFn: ({ signal }) => contextPackApi.read(selection, selected, signal) })
  const overBudget = preview.error instanceof ApiRequestError && preview.error.code === 'mandatory_context_over_budget'
  const failed = history.isError || archive.isError || (preview.isError && !overBudget)
  useEffect(() => { if (failed) onFailure(true) }, [failed, onFailure])
  const write = useMutation({ retry: false, mutationFn: ({ view, attempt }: { view: ContextPreview; attempt: string }) => contextPackApi.archive(view, attempt),
    onSuccess: (id) => { setSelected(id); setRequested(null); void client.invalidateQueries({ queryKey: [...prefix, 'history'] }) },
    onSettled: () => setConsent('') })
  const view = requested && !preview.isFetching && !preview.isError ? preview.data : undefined
  const consentKey = JSON.stringify([view?.input_digest, preview.dataUpdatedAt])
  const confirmed = !!view && consent === consentKey
  const canPreview = Number.isInteger(Number(budget)) && Number(budget) >= 512 && Number(budget) <= 32768 && !write.isPending && !preview.isFetching
  const canSave = !!view && confirmed && write.isIdle
  return { open, budget, history, preview, archive, view, selected, write, overBudget, confirmed, canPreview, canSave,
    stale: write.error instanceof StaleContextPreview, page: cursors.length,
    archived: !archive.isError && !archive.isFetching ? archive.data : undefined,
    toggle: () => { setOpen(!open); setConsent('') },
    editBudget: (value: string) => { setBudget(value); setRequested(null); setConsent('') },
    inspect: () => { if (!canPreview) return; setSelected(''); setConsent(''); submitted.current = false; write.reset();
      setRequested({ ...selection, purpose: 'test_design', policy_revision: publicationId ? (retrievalBindings ? 'nasus.test-design-context.v5' : 'nasus.test-design-context.v4') : 'nasus.test-design-context.v3',
        ...(publicationId ? { publication_id: publicationId } : {}), ...(retrievalBindings ? { retrieval_bindings: retrievalBindings } : {}),
        max_tokens: Number(budget), candidate_limit: 5 });
      setGeneration((value) => value + 1) },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    save: () => { if (canSave && view && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ view, attempt: crypto.randomUUID() }) } },
    choose: (id: string) => { setSelected(id); setRequested(null); setConsent('') },
    reload: () => { setConsent(''); void history.refetch(); if (selected) void archive.refetch() },
    previous: cursors.length > 1 ? () => setCursors(cursors.slice(0, -1)) : undefined,
    next: history.data?.next_after_id ? () => setCursors([...cursors, history.data!.next_after_id!]) : undefined,
  }
}
