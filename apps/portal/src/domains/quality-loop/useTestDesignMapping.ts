import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { StaleTestDesignMapping, testDesignMappingApi } from './testDesignMappingApi'
import { mappingsValid, newAssertionReviews } from './testDesignMappingValidation'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { AssertionReview, MappingReview } from './types/testDesignMapping'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useTestDesignMapping(draft: GenerationArchive, sessionId: string, onFailure: () => void) {
  const m = draft.metadata, submitted = useRef(false)
  const [open, setOpen] = useState(false), [editing, setEditing] = useState(false), [selected, setSelected] = useState('')
  const [decision, setDecision] = useState<'review' | 'withdraw'>('review'), [values, setValues] = useState<AssertionReview[]>([])
  const [reason, setReason] = useState(''), [consent, setConsent] = useState('')
  const prefix = ['test-design-mapping', m.project_id, sessionId, m.generation_id, m.artifact_hash]
  const query = useQuery({ ...sensitive, enabled: open, queryKey: prefix,
    queryFn: ({ signal }) => testDesignMappingApi.inspect(draft, signal) })
  const view = !query.isFetching && !query.isError ? query.data : undefined
  const revision = view?.history.find((item) => item.revision_id === selected)
  const archive = useQuery({ ...sensitive, enabled: open && !!revision, queryKey: [...prefix, selected],
    queryFn: ({ signal }) => testDesignMappingApi.read(draft, revision!, signal) })
  const failed = query.isError || archive.isError
  useEffect(() => { if (failed) onFailure() }, [failed, onFailure])
  const write = useMutation({ retry: false,
    mutationFn: ({ input, attempt }: { input: MappingReview; attempt: string }) => testDesignMappingApi.record(input, attempt),
    onSuccess: () => { setEditing(false); setValues([]); setSelected(''); setReason('') },
    onSettled: () => { setConsent(''); void query.refetch() } })
  const content = view && !archive.isFetching && !archive.isError ? (selected ? archive.data : view.head) : undefined
  const busy = query.isFetching || archive.isFetching || write.isPending
  const mayReview = !!view?.can_review && view.scope_current
    && draft.result.proposal.cases.reduce((sum, item) => sum + item.assertions.length, 0) <= 8192
  const consentKey = JSON.stringify([m, query.dataUpdatedAt, view?.head?.revision, decision, values, reason])
  const confirmed = !!view && consentKey === consent
  const validReason = !!reason.trim() && [...reason].length <= 2000
  const canSubmit = editing && !!view?.can_review && !selected && !busy && write.isIdle && confirmed && validReason
    && (decision === 'withdraw' ? view.head?.revision.status === 'reviewed' : mayReview && mappingsValid(values, draft))
  const reset = () => { submitted.current = false; setConsent(''); write.reset() }
  return { open, view, content, selected, editing, values, decision, reason, busy, confirmed, canSubmit, mayReview, write,
    stale: write.error instanceof StaleTestDesignMapping,
    toggle: () => { if (!busy) { setOpen(!open); setConsent('') } },
    reload: () => { if (!write.isPending) { reset(); void query.refetch(); if (selected) void archive.refetch() } },
    choose: (id: string) => { if (!busy) { setSelected(id); setEditing(false); setValues([]); setConsent('') } },
    begin: (withdraw = false) => {
      if (busy || !view?.can_review || (withdraw ? view.head?.revision.status !== 'reviewed' : !mayReview)) return
      reset(); setSelected(''); setEditing(true); setDecision(withdraw ? 'withdraw' : 'review'); setReason('')
      const original = view.head && 'mappings' in view.head.request ? view.head.request.mappings : null
      setValues(withdraw ? [] : structuredClone(original ?? newAssertionReviews(draft)))
    },
    edit: (index: number, changes: Pick<AssertionReview, 'decision' | 'reason'>) => {
      if (!busy && write.isIdle) { setConsent(''); setValues(values.map((value, i) => i === index ? { ...value, ...changes } : value)) }
    },
    explain: (value: string) => { setConsent(''); setReason(value) },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    submit: () => {
      if (canSubmit && view && !submitted.current) {
        submitted.current = true; setConsent('')
        write.mutate({ attempt: crypto.randomUUID(), input: { project_id: m.project_id, generation_id: m.generation_id,
          generation_artifact_hash: m.artifact_hash, expected_previous_revision_id: view.head?.revision.revision_id ?? null,
          decision, mappings: decision === 'review' ? values : null, reason, policy_revision: 'nasus.test-design-mapping.v1' } })
      }
    },
  }
}
