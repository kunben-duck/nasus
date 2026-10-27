import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import { platformApi } from '../platform/api'
import { automationScriptApi } from './automationScriptApi'
import { readAutomationInput } from './automationInputApi'
import { caseApprovalApi } from './caseApprovalApi'
import { generationEqual } from './testDesignGenerationValidation'
import { budgetValue, type BudgetField } from './useTestDesignGeneration'
import type { ScriptPreview, ScriptSelection } from './types/automationScripts'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useAutomationScripts(draft: GenerationArchive, mapping: RecordedMappingArchive, sessionId: string, onFailure: () => void) {
  const [open, setOpen] = useState(false), [model, setModel] = useState(''), [selected, setSelected] = useState('')
  const [commandId, setCommandId] = useState(''), [consent, setConsent] = useState(''), submitted = useRef(false)
  const [protocol, setProtocol] = useState<'v1' | 'v2' | 'v3'>('v1')
  const [fields, setFields] = useState<Record<BudgetField, string>>({ currency: 'USD', calls: '1', input: '', output: '', tokens: '', cost: '' })
  const m = mapping.revision, prefix = ['automation-script-revisions', m.project_id, sessionId, m.revision_id, m.artifact_hash]
  const current = draft.current_use.scope_current && mapping.current_use.scope_current && mapping.current_use.mapping_current && mapping.current_use.mapping_complete
  const history = useInfiniteQuery({ ...sensitive, enabled: open, queryKey: prefix, initialPageParam: '',
    queryFn: ({ pageParam, signal }) => automationScriptApi.history(mapping, pageParam, signal),
    getNextPageParam: (page) => page.next_after_id ?? undefined,
    refetchInterval: (query) => query.state.data?.pages.some((page) => page.items.some((item) => item.status === 'running')) ? 10000 : false })
  const rows = !history.isFetching && !history.isError ? history.data?.pages.flatMap((page) => page.items) : undefined
  const item = rows?.find((row) => row.invocation_id === selected)
  const archive = useQuery({ ...sensitive, enabled: open && !!item?.script_revision_id, queryKey: [...prefix, 'draft', selected, item?.artifact_hash],
    queryFn: ({ signal }) => automationScriptApi.read(draft, mapping, item!, signal) })
  // Consent-bound verification must not observe the adjacent read-only preview's cache.
  const input = useQuery({ ...sensitive, enabled: open && current, queryKey: ['automation-script-input', m.project_id, sessionId,
    draft.metadata.generation_id, draft.metadata.artifact_hash, m.revision_id, m.artifact_hash], queryFn: ({ signal }) => readAutomationInput(draft, mapping, signal) })
  const admission = useQuery({ ...sensitive, enabled: open && current, queryKey: ['test-design-case-approvals', m.project_id, sessionId,
    m.revision_id, m.artifact_hash], queryFn: ({ signal }) => caseApprovalApi.preview(draft, mapping, signal) })
  const models = useQuery({ ...sensitive, enabled: open && current, queryKey: ['generation-models', sessionId],
    queryFn: ({ signal }) => platformApi.getModelConfigurations('chat', signal) })
  const choices = !models.isError && !models.isFetching ? models.data?.configurations.filter((c) => c.route === 'chat'
    && !c.legacy_imported && c.last_test_result.ok && !!c.last_test_signature) ?? [] : []
  const chosen = choices.find((c) => c.config_id === model), budget = budgetValue(fields)
  const inputValue = current && !input.isFetching && !input.isError ? input.data : undefined
  const admissionValue = current && !admission.isFetching && !admission.isError ? admission.data : undefined
  const head = admissionValue?.head
  const admitted = !!(inputValue && admissionValue?.input_current && head?.status === 'approved'
    && head.input_digest === inputValue.input_digest && head.mapping_revision_id === m.revision_id
    && generationEqual(admissionValue.prepared, inputValue))
  const selection: ScriptSelection | null = chosen && budget && inputValue && admitted && head ? { project_id: m.project_id,
    mapping_revision_id: m.revision_id, mapping_artifact_hash: m.artifact_hash, case_ids: inputValue.selected_case_ids, model_config_id: model, budget,
    case_approval_revision_id: head.revision_id, case_approval_artifact_hash: head.artifact_hash,
    ...(protocol === 'v3' ? { http_protocol: 'nasus.runner-http-execution.v3' as const }
      : protocol === 'v2' ? { http_protocol: 'nasus.runner-http-execution.v2' as const } : {}) } : null
  const key = JSON.stringify([selection, chosen, inputValue?.input_digest])
  const preview = useMutation({ retry: false, mutationFn: async ({ selection, key }: { selection: ScriptSelection; key: string }) =>
    ({ value: await automationScriptApi.preview(selection, inputValue!), key, attempt: crypto.randomUUID() }) })
  const prepared = inputValue && admitted && choices.length && preview.data?.key === key && !preview.isError ? preview.data : undefined
  const confirmationKey = JSON.stringify([prepared, input.dataUpdatedAt, admission.dataUpdatedAt, models.dataUpdatedAt, history.dataUpdatedAt, mapping.current_use])
  const confirmed = !!prepared && consent === confirmationKey
  const write = useMutation({ retry: false, mutationFn: ({ value, attempt }: { value: ScriptPreview; attempt: string }) =>
    automationScriptApi.generate(value, attempt, setCommandId), onSuccess: (id) => setSelected(id),
    onSettled: () => { setConsent(''); void history.refetch() } })
  const failed = open && (history.isError || archive.isError || input.isError || admission.isError)
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const busy = open && (preview.isPending || write.isPending || history.isFetching || archive.isFetching || input.isFetching || admission.isFetching || models.isFetching)
  const active = !!history.data?.pages.some((page) => page.items.some((row) => row.status === 'running'))
  const mayPreview = !!selection && current && !!rows && !active && !history.hasNextPage && !busy && !failed
  const canStart = mayPreview && !!prepared && confirmed && write.isIdle
  const reset = () => { setConsent(''); preview.reset(); write.reset(); submitted.current = false }
  return { open, history, rows, item, selected, archive, models, choices, model, protocol, fields, preview, prepared, confirmed, write, commandId,
    current, admitted, busy, active, failed, mayPreview, canStart,
    result: rows && !archive.isFetching && !archive.isError && !failed ? archive.data : undefined,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    reload: () => { if (!write.isPending) { reset(); void history.refetch(); if (item?.script_revision_id) void archive.refetch(); if (current) { void input.refetch(); void admission.refetch(); void models.refetch() } } },
    loadMore: () => { if (!busy && history.hasNextPage) void history.fetchNextPage() },
    choose: (id: string) => { if (!busy) { setSelected(id); setConsent('') } },
    chooseModel: (id: string) => { if (!busy) { reset(); setModel(id) } },
    chooseProtocol: (value: string) => { if (!busy && (value === 'v1' || value === 'v2' || value === 'v3')) { reset(); setProtocol(value) } },
    editBudget: (field: BudgetField, value: string) => { if (!busy) { reset(); setFields({ ...fields, [field]: value }) } },
    prepare: () => { if (mayPreview && selection) { reset(); preview.mutate({ selection, key }) } },
    confirm: (checked: boolean) => setConsent(checked ? confirmationKey : ''),
    start: () => { if (canStart && prepared && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ value: prepared.value, attempt: prepared.attempt }) } },
  }
}
