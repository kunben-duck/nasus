import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { canonicalDigest } from '../../shared/utils/canonicalDigest'
import { platformApi } from '../platform/api'
import type { ContextArchive } from '../system-image/types/contextPack'
import { budgetValue, type BudgetField } from './useTestDesignGeneration'
import { scopeDraftApi, type ScopeDraftPreview, type ScopeDraftSelection } from './scopeDraftApi'
import { scopeDraftRecovery, type ScopeDraftAttempt } from './scopeDraftRecovery'
import { requireScopeDraft } from './scopeDraftValidation'
import { generationEqual } from './testDesignGenerationValidation'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useScopeDraft(context: ContextArchive, sessionId: string, actorId: string) {
  const [model, setModel] = useState(''), [selected, setSelected] = useState(''), [consent, setConsent] = useState('')
  const submitted = useRef(false), live = useRef(true)
  const scope = { projectId: context.metadata.project_id, contextId: context.metadata.context_id, contextHash: context.metadata.artifact_hash }
  const [stored, setStored] = useState(() => {
    try { return { attempt: scopeDraftRecovery.read(actorId, scope), invalid: false } }
    catch { return { attempt: null, invalid: true } }
  })
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const [fields, setFields] = useState<Record<BudgetField, string>>({ currency: 'USD', calls: '1', input: '', output: '', tokens: '', cost: '' })
  const m = context.metadata, prefix = ['scope-drafts', actorId, m.project_id, m.context_id, sessionId, m.artifact_hash]
  const models = useQuery({ ...sensitive, queryKey: ['generation-models', sessionId], queryFn: ({ signal }) => platformApi.getModelConfigurations('chat', signal) })
  const history = useQuery({ ...sensitive, queryKey: prefix, queryFn: ({ signal }) => scopeDraftApi.history(context, signal) })
  const choices = !models.isFetching && !models.isError ? models.data?.configurations.filter((item) => !item.legacy_imported
    && item.last_test_result.ok && !!item.last_test_signature) ?? [] : []
  const current = !context.current_use.stale, budget = budgetValue(fields), chosen = choices.find((item) => item.config_id === model)
  const selection: ScopeDraftSelection | null = chosen && budget && current ? { project_id: m.project_id, context_id: m.context_id,
    context_artifact_hash: m.artifact_hash, model_config_id: model, budget } : null
  const key = JSON.stringify([selection, chosen])
  const preview = useMutation({ retry: false, mutationFn: async ({ input, key }: { input: ScopeDraftSelection; key: string }) =>
    ({ value: await scopeDraftApi.preview(input), key, attempt: crypto.randomUUID() }) })
  const prepared = preview.data?.key === key && !preview.isError ? preview.data : undefined
  const consentKey = JSON.stringify([prepared, models.dataUpdatedAt, history.dataUpdatedAt])
  const confirmed = !!prepared && consent === consentKey
  const write = useMutation({ retry: false, mutationFn: async ({ value, attempt }: { value: ScopeDraftPreview; attempt: string }) => {
    const saved: ScopeDraftAttempt = { ...scope, requestKey: attempt, requestHash: await canonicalDigest(value.request) }
    requireScopeDraft(live.current); scopeDraftRecovery.save(actorId, saved); setStored({ attempt: saved, invalid: false })
    return scopeDraftApi.generate(value.request, saved, (next) => {
      scopeDraftRecovery.acknowledge(actorId, next); requireScopeDraft(live.current); setStored({ attempt: next, invalid: false })
    })
  }, onSuccess: (result) => { if (live.current && result.command.status === 'completed') setSelected(result.command.id) },
    onSettled: () => { if (live.current) { setConsent(''); void history.refetch() } } })
  const recovery = useQuery({ ...sensitive, enabled: !!stored.attempt && !write.isPending,
    queryKey: [...prefix, 'original', stored.attempt?.requestKey, history.dataUpdatedAt], queryFn: async ({ signal }) => {
      requireScopeDraft(stored.attempt)
      const result = await scopeDraftApi.recover(stored.attempt, signal)
      signal.throwIfAborted(); requireScopeDraft(live.current); scopeDraftRecovery.acknowledge(actorId, result.attempt)
      return result
    }, refetchInterval: (query) => ['pending', 'running'].includes(query.state.data?.command.status ?? '') ? 5000 : false })
  const original = !write.isPending && !recovery.isError && !recovery.isFetching ? recovery.data : undefined
  const originalPreview = useMutation({ retry: false, mutationFn: async () => {
    requireScopeDraft(original?.command.status === 'waiting_confirmation')
    const { project_id, context_id, context_artifact_hash, model_config_id, budget } = original.input
    const value = await scopeDraftApi.preview({ project_id, context_id, context_artifact_hash, model_config_id, budget })
    requireScopeDraft(generationEqual(value.request, original.input))
    return { value, commandId: original.command.id }
  } })
  const originalValue = original?.command.status === 'waiting_confirmation' && !originalPreview.isError
    && originalPreview.data?.commandId === original.command.id ? originalPreview.data.value : undefined
  const originalConsentKey = JSON.stringify([originalValue, recovery.dataUpdatedAt, history.dataUpdatedAt])
  const originalConfirmed = !!originalValue && consent === originalConsentKey
  const resume = useMutation({ retry: false, mutationFn: async () => {
    requireScopeDraft(original && originalValue && originalConfirmed && live.current)
    return scopeDraftApi.confirmOriginal(original.attempt)
  }, onSuccess: (result) => { if (live.current && result.command.status === 'completed') setSelected(result.command.id) },
    onSettled: () => { if (live.current) { setConsent(''); void history.refetch(); void recovery.refetch() } } })
  const rows = !history.isError && !history.isFetching ? history.data : undefined
  const item = rows?.find((row) => row.invocation_id === selected)
  const archive = useQuery({ ...sensitive, enabled: item?.status === 'draft', queryKey: [...prefix, selected],
    queryFn: ({ signal }) => scopeDraftApi.read(context, selected, signal) })
  const busy = preview.isPending || write.isPending || history.isFetching || models.isFetching || archive.isFetching
    || recovery.isFetching || originalPreview.isPending || resume.isPending
  const unknown = rows?.some((row) => row.provider_outcome_unknown || row.status === 'reply_archived')
  const editable = !stored.attempt && !stored.invalid && !busy
  const mayPreview = !!selection && !!rows && editable && !unknown
  const canStart = mayPreview && !!prepared && confirmed && write.isIdle
  const reset = () => { setConsent(''); preview.reset(); write.reset(); submitted.current = false }
  const mayResume = !!originalValue && originalConfirmed && !busy && current && !!rows && resume.isIdle
  const mayClear = !!original && !!rows && !busy && (original.command.status === 'completed'
    && rows.some((row) => row.invocation_id === original.command.id && row.status === 'draft')
    || ['failed', 'cancelled'].includes(original.command.status) && original.command.input_payload.confirmed_by_user !== true)
  return { fields, model, models, choices, rows, history, archive, preview, prepared, write, busy, editable, confirmed, mayPreview, canStart, selected,
    stored, recovery, original, originalPreview, originalValue, originalConfirmed, resume, mayResume, mayClear,
    result: rows && !archive.isError && !archive.isFetching ? archive.data : undefined,
    chooseModel: (id: string) => { if (editable) { reset(); setModel(id) } },
    editBudget: (field: BudgetField, value: string) => { if (editable) { reset(); setFields({ ...fields, [field]: value }) } },
    prepare: () => { if (mayPreview && selection) { reset(); preview.mutate({ input: selection, key }) } },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    start: () => { if (canStart && prepared && !submitted.current) { submitted.current = true; write.mutate({ value: prepared.value, attempt: prepared.attempt }) } },
    verifyOriginal: () => { if (!busy && original?.command.status === 'waiting_confirmation') { setConsent(''); submitted.current = false; originalPreview.mutate() } },
    confirmOriginal: (checked: boolean) => setConsent(checked ? originalConsentKey : ''),
    resumeOriginal: () => { if (mayResume && !submitted.current) { submitted.current = true; resume.mutate() } },
    another: () => { if (mayClear && original) {
      scopeDraftRecovery.clear(actorId, original.attempt); setStored({ attempt: null, invalid: false }); reset(); originalPreview.reset(); resume.reset()
    } },
    choose: (id: string) => { if (!busy) { setSelected(id); setConsent('') } },
    reload: () => { if (!busy) {
      reset(); originalPreview.reset(); resume.reset()
      try { setStored({ attempt: scopeDraftRecovery.read(actorId, scope), invalid: false }) } catch { setStored({ attempt: null, invalid: true }) }
      void history.refetch(); void models.refetch(); if (stored.attempt) void recovery.refetch(); if (item?.status === 'draft') void archive.refetch()
    } },
  }
}
