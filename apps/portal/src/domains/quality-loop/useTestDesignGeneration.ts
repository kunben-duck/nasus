import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import { platformApi } from '../platform/api'
import type { ScopeArchive } from './types/testDesignScope'
import type { GenerationBudget, GenerationPreview, GenerationRecovery, GenerationSelection } from './types/testDesignGeneration'
import { testDesignGenerationApi } from './testDesignGenerationApi'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export type BudgetField = 'currency' | 'calls' | 'input' | 'output' | 'tokens' | 'cost'
export function budgetValue(fields: Record<BudgetField, string>): GenerationBudget | null {
  if (!['USD', 'CNY'].includes(fields.currency) || !/^\d+(\.\d{1,9})?$/.test(fields.cost)) return null
  const [units, fraction = ''] = fields.cost.split('.')
  const cost = Number(BigInt(units) * 1000000000n + BigInt(fraction.padEnd(9, '0')))
  const input = Number(fields.input), output = Number(fields.output), tokens = Number(fields.tokens)
  const calls = Number(fields.calls)
  if (![cost, calls, input, output, tokens].every(Number.isSafeInteger) || calls < 1 || calls > 64 || cost < 1 || cost > 9e15
    || input < 512 || input > 1e6 || output < 512 || output > 32768 || tokens < 1024 || tokens > 64e6) return null
  return { currency: fields.currency as 'USD' | 'CNY', max_calls: calls, max_reserved_tokens: tokens, max_reserved_cost_nanos: cost,
    max_input_tokens_per_call: input, max_output_tokens_per_call: output }
}
export function useTestDesignGeneration(scope: ScopeArchive, sessionId: string) {
  const [open, setOpen] = useState(false), [model, setModel] = useState(''), [selected, setSelected] = useState('')
  const [mappingFailed, setMappingFailed] = useState(false)
  const [fields, setFields] = useState<Record<BudgetField, string>>({ currency: 'USD', calls: '1', input: '', output: '', tokens: '', cost: '' })
  const [consent, setConsent] = useState(''), [controlConsent, setControlConsent] = useState(''), submitted = useRef(false)
  const models = useQuery({ ...sensitive, enabled: open, queryKey: ['generation-models', sessionId], queryFn: ({ signal }) => platformApi.getModelConfigurations('chat', signal) })
  const choices = !models.isFetching && !models.isError ? models.data?.configurations.filter((c) => c.route === 'chat'
    && !c.legacy_imported && c.last_test_result.ok && !!c.last_test_signature) ?? [] : []
  const chosen = choices.find((c) => c.config_id === model), budget = budgetValue(fields)
  const selection: GenerationSelection | null = chosen && budget ? { project_id: scope.revision.project_id,
    scope_revision_id: scope.revision.revision_id, scope_artifact_hash: scope.revision.artifact_hash, model_config_id: model, budget } : null
  const key = JSON.stringify([selection, chosen]), prefix = ['generation-jobs', scope.revision.project_id, sessionId, scope.revision.revision_id, scope.revision.artifact_hash]
  const history = useInfiniteQuery({ ...sensitive, enabled: open, queryKey: prefix, initialPageParam: '',
    queryFn: ({ pageParam, signal }) => testDesignGenerationApi.historyPage(scope, pageParam, signal),
    getNextPageParam: (page) => page.next_after_id ?? undefined,
    refetchInterval: (query) => query.state.data?.pages.some((page) => page.has_running) ? 5000 : false })
  const loaded = !history.isFetching && !history.isError ? history.data?.pages.flatMap((page) => page.items) : undefined
  // Command IDs are cursor keys, not timestamps. Keep a newly acknowledged job
  // selected even when it is outside the explicitly loaded history pages.
  const id = selected || loaded?.find((row) => row.status === 'running')?.invocation_id
    || loaded?.find((row) => row.tool_id === 'quality.test_design.recover' && row.status === 'completed')?.invocation_id
    || loaded?.find((row) => row.status === 'completed')?.invocation_id || loaded?.at(-1)?.invocation_id || ''
  const jobQuery = useQuery({ ...sensitive, enabled: open && !!id, queryKey: [...prefix, 'job', id],
    queryFn: ({ signal }) => testDesignGenerationApi.job(scope, id, signal),
    refetchInterval: (query) => query.state.data?.status === 'running' ? 3000 : false })
  const job = loaded && !jobQuery.isFetching && !jobQuery.isError ? jobQuery.data : undefined
  const rows = loaded && !jobQuery.isError ? loaded.map((row) => ({ id: row.invocation_id, status: row.status })) : undefined
  if (rows && job && !rows.some((row) => row.id === job.invocation_id)) rows.push({ id: job.invocation_id, status: job.status })
  const refreshHistory = history.refetch, previousJob = useRef<{ id: string; status: string } | null>(null)
  useEffect(() => {
    if (!job) return
    if (job.status !== 'running' && previousJob.current?.id === job.invocation_id && previousJob.current.status === 'running') {
      void refreshHistory()
    }
    previousJob.current = { id: job.invocation_id, status: job.status }
  }, [job, refreshHistory])
  const archive = useQuery({ ...sensitive, enabled: open && !!job?.generation_id, queryKey: [...prefix, 'result', id, job?.generation_id],
    queryFn: ({ signal }) => testDesignGenerationApi.result(scope, job!, signal) })
  const result = !mappingFailed && job && !archive.isFetching && !archive.isError ? archive.data : undefined
  const preview = useMutation({ retry: false, mutationFn: async ({ selection, key }: { selection: GenerationSelection; key: string }) =>
    ({ preview: await testDesignGenerationApi.preview(selection), key, attempt: crypto.randomUUID() }) })
  const prepared = chosen && preview.data?.key === key && !preview.isError ? preview.data : undefined
  const consentKey = JSON.stringify([prepared, models.dataUpdatedAt, scope.current_use]), confirmed = !!prepared && consentKey === consent
  const write = useMutation({ retry: false, mutationFn: ({ value, attempt }: { value: GenerationPreview; attempt: string }) => testDesignGenerationApi.start(value, attempt),
    onSuccess: (next) => setSelected(next), onSettled: () => { setConsent(''); void history.refetch() } })
  const recovery = useMutation({ retry: false, mutationFn: ({ value, attempt }: { value: GenerationRecovery; attempt: string }) => testDesignGenerationApi.recover(value, attempt),
    onSuccess: (next) => setSelected(next), onSettled: () => { setControlConsent(''); void history.refetch() } })
  const cancel = useMutation({ retry: false, mutationFn: ({ id, attempt }: { id: string; attempt: string }) => testDesignGenerationApi.cancel(scope.revision.project_id, id, attempt),
    onSettled: () => { setControlConsent(''); void jobQuery.refetch(); void history.refetch() } })
  const busy = preview.isPending || write.isPending || recovery.isPending || cancel.isPending
  const active = history.data?.pages.some((page) => page.has_running) || jobQuery.data?.status === 'running'
  const runningOutsidePage = !!active && !!rows && !rows.some((row) => row.status === 'running')
  const controlKey = JSON.stringify(job), controlConfirmed = !!job && controlConsent === controlKey
  const current = scope.current_use.scope_current && scope.current_use.scope_complete
  const canStart = !mappingFailed && !!prepared && confirmed && current && !!rows && !active && !busy && write.isIdle
    && !jobQuery.isFetching && !jobQuery.isError && !archive.isError
  const reset = () => { setConsent(''); setControlConsent(''); preview.reset(); write.reset(); submitted.current = false }
  return { open, models, choices, model, fields, history, rows: mappingFailed ? undefined : rows, selected: id, jobQuery,
    job: mappingFailed ? undefined : job, archive, result, preview, prepared: mappingFailed ? undefined : prepared, confirmed, mappingFailed,
    onMappingFailure: () => setMappingFailed(true),
    write, recovery, cancel, busy, active, runningOutsidePage, current, canStart, controlConfirmed,
    mayPreview: !mappingFailed && !!selection && current && !busy && !!rows && !active && !archive.isError,
    toggle: () => { if (!busy) { setOpen(!open); setConsent(''); setControlConsent('') } },
    chooseModel: (id: string) => { if (!busy) { setModel(id); reset() } },
    editBudget: (field: BudgetField, value: string) => { if (!busy) { setFields({ ...fields, [field]: value }); reset() } },
    prepare: () => { if (!mappingFailed && selection && current && !busy && rows && !active && !archive.isError) { reset(); preview.mutate({ selection, key }) } },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    confirmControl: (checked: boolean) => setControlConsent(checked ? controlKey : ''),
    start: () => { if (canStart && prepared && !submitted.current) { submitted.current = true; write.mutate({ value: prepared.preview, attempt: prepared.attempt }) } },
    chooseJob: (id: string) => { if (!busy) { setSelected(id); setControlConsent('') } },
    loadMore: () => { if (!busy && !history.isFetching && history.hasNextPage) void history.fetchNextPage() },
    reload: () => { if (!busy) { reset(); setMappingFailed(false); recovery.reset(); cancel.reset(); void models.refetch(); void history.refetch(); if (id) void jobQuery.refetch(); if (job?.generation_id) void archive.refetch() } },
    stop: () => { if (job?.status === 'running' && controlConfirmed && !busy && cancel.isIdle) cancel.mutate({ id: job.invocation_id, attempt: crypto.randomUUID() }) },
    resume: () => { if (job?.recovery_request && current && controlConfirmed && !busy && recovery.isIdle) recovery.mutate({ value: job.recovery_request, attempt: crypto.randomUUID() }) },
  }
}
