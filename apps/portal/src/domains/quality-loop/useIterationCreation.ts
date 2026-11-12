import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { imageRollbackApi } from '../system-image/imageRollbackApi'
import { iterationAttemptKey, readIterationAttempt, verifyIterationInput } from './iterationCreation'
import { iterationCreationApi } from './iterationCreationApi'
import type { IterationCreateAttempt, IterationCreateInput } from './types/delivery'

export function useIterationCreation(projectId: string, actorId: string) {
  const client = useQueryClient(), submitted = useRef(false)
  const [restored] = useState(() => {
    try { return { attempt: readIterationAttempt(window.sessionStorage, projectId, actorId), error: false } }
    catch { return { attempt: null, error: true } }
  })
  const [attempt, setAttempt] = useState(restored.attempt)
  const [storageError, setStorageError] = useState(restored.error)
  const [name, setName] = useState(''), [baselineId, setBaselineId] = useState('')
  const [publicationId, setPublicationId] = useState(''), [consent, setConsent] = useState('')
  const history = useQuery({ queryKey: ['iteration-publications', projectId, actorId, baselineId],
    enabled: !!baselineId && !attempt, gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => imageRollbackApi.history(projectId, baselineId, 0, signal) })
  const head = !history.isFetching && !history.isError ? history.data?.head : undefined
  const selected = head && publicationId === head.publication_id ? head : undefined
  const input: IterationCreateInput | null = selected ? { project_id: projectId, name: name.trim(), image_binding: {
    publication_id: selected.publication_id, image_revision_id: selected.image_revision_id,
    image_artifact_hash: selected.image_artifact_hash, expected_head_id: selected.publication_id,
  } } : null
  const consentKey = JSON.stringify([input, history.dataUpdatedAt])
  const confirmed = !!input && consent === consentKey

  function save(value: IterationCreateAttempt) {
    window.sessionStorage.setItem(iterationAttemptKey(projectId, actorId), JSON.stringify(value))
    setAttempt(value)
  }
  const write = useMutation({ retry: false,
    mutationFn: ({ value, mode }: { value: IterationCreateAttempt; mode: 'submit' | 'inspect' | 'confirm' }) =>
      iterationCreationApi.execute(value, mode, save),
    onSuccess: (result) => {
      if (result.delivery) {
        void client.invalidateQueries({ queryKey: ['project', projectId] })
        void client.invalidateQueries({ queryKey: ['delivery-iterations', projectId] })
        void client.invalidateQueries({ queryKey: ['version-delivery', projectId] })
      }
    }, onSettled: () => { submitted.current = false; setConsent('') } })

  function execute(mode: 'submit' | 'inspect' | 'confirm') {
    if (submitted.current || storageError) return
    if (!attempt && (!confirmed || !input || !name.trim())) return
    const value = attempt ?? { actor_id: actorId, input: verifyIterationInput(input!), idempotency_key: crypto.randomUUID() }
    try { save(value) } catch { setStorageError(true); return }
    submitted.current = true
    setConsent('')
    write.mutate({ value, mode })
  }
  function reset() {
    if (!write.data || (!write.data.delivery && !['failed', 'cancelled'].includes(write.data.receipt.status))) return
    try { window.sessionStorage.removeItem(iterationAttemptKey(projectId, actorId)) } catch { setStorageError(true); return }
    setAttempt(null); setConsent(''); setPublicationId(''); write.reset(); void history.refetch()
  }
  return { name, baselineId, publicationId, head, selected, history, write, attempt, confirmed, storageError,
    canCreate: !!input && !!name.trim() && confirmed && !attempt && !storageError && !write.isPending,
    setName: (value: string) => { setName(value); setConsent('') },
    chooseBaseline: (value: string) => { setBaselineId(value); setPublicationId(''); setConsent('') },
    choosePublication: (value: string) => { setPublicationId(value); setConsent('') },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''), execute, reset }
}
