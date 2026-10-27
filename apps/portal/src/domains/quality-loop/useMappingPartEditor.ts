import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { mappingStagingApi } from './mappingStagingApi'
import { mappingQuery, partDecisionsValid } from './mappingStagingValidation'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { AssertionReview } from './types/testDesignMapping'
import type { MappingWorkspace, MappingPartStage } from './types/mappingStaging'

export function useMappingPartEditor(draft: GenerationArchive, workspace: MappingWorkspace, sequence: number, onFailure: () => void, onSaved: () => void) {
  const [editing, setEditing] = useState(false), [selected, setSelected] = useState('')
  const [values, setValues] = useState<AssertionReview[]>([]), [consent, setConsent] = useState(''), submitted = useRef(false)
  const pin = workspace.plan.generation_pin, prefix = ['mapping-part-editor', pin.project_id, workspace.actorId, pin.generation_id, workspace.plan.plan_digest, sequence]
  const query = useQuery({ queryKey: prefix, gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
    queryFn: ({ signal }) => mappingStagingApi.part(draft, workspace, sequence, signal) })
  const view = !query.isFetching && !query.isError ? query.data : undefined
  const revision = view?.head.history.find((r) => r.part_revision_id === selected)
  const archive = useQuery({ queryKey: [...prefix, selected], gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always', enabled: !!revision,
    queryFn: ({ signal }) => mappingStagingApi.read(workspace, view!.part, revision!, signal) })
  const failed = query.isError || archive.isError
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const write = useMutation({ retry: false, mutationFn: ({ input, attempt }: { input: MappingPartStage; attempt: string }) => mappingStagingApi.record(input, attempt),
    onSuccess: () => { setEditing(false); setValues([]); setSelected(''); onSaved() },
    onSettled: () => { setConsent(''); void query.refetch() } })
  const busy = query.isFetching || archive.isFetching || write.isPending
  const content = view && !archive.isFetching && !archive.isError ? (selected ? archive.data : view.archive) : undefined
  const key = JSON.stringify([workspace.plan.plan_digest, query.dataUpdatedAt, view?.head.head, sequence, values])
  const confirmed = consent === key, editable = !!view?.head.scope_current && workspace.scopeCurrent
  const canSubmit = editing && editable && !selected && !busy && write.isIdle && confirmed && !!view && partDecisionsValid(view.part, values)
  const reset = () => { submitted.current = false; write.reset(); setConsent('') }
  return { view, content, selected, editing, values, busy, confirmed, canSubmit, editable, write,
    begin: () => { if (editable && !busy) { reset(); setSelected(''); setEditing(true)
      setValues(structuredClone(view!.archive?.request.decisions ?? view!.part.assertions.map((a) => ({ ...a, decision: 'defer' as const, reason: '' })))) } },
    choose: (id: string) => { if (!busy) { setSelected(id); setEditing(false); setValues([]); setConsent('') } },
    edit: (index: number, changes: Pick<AssertionReview, 'decision' | 'reason'>) => {
      if (!busy && write.isIdle) { setConsent(''); setValues(values.map((v, i) => i === index ? { ...v, ...changes } : v)) }
    },
    confirm: (checked: boolean) => setConsent(checked ? key : ''),
    reload: () => { if (!write.isPending) { reset(); setEditing(false); setValues([]); void query.refetch(); if (selected) void archive.refetch() } },
    submit: () => { if (canSubmit && view && !submitted.current) {
      submitted.current = true; setConsent(''); write.mutate({ attempt: crypto.randomUUID(), input: { ...mappingQuery(workspace),
        plan_digest: workspace.plan.plan_digest, expected_previous_revision_id: workspace.plan.expected_previous_revision_id,
        sequence, part_digest: view.part.part_digest, expected_previous_part_revision_id: view.head.head?.part_revision_id ?? null,
        decisions: values, policy_revision: 'nasus.test-design-mapping-staging.v1' } })
    } },
  }
}
