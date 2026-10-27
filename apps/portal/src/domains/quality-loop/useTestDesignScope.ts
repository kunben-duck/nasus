import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ContextArchive } from '../system-image/types/contextPack'
import { newScopeContract, scopeContractValid, scopeTextValid } from './testDesignScopeDraft'
import { StaleTestDesignScope, testDesignScopeApi } from './testDesignScopeApi'
import type { ScopeReview, TestDesignContract } from './types/testDesignScope'

const sensitive = { gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export function useTestDesignScope(context: ContextArchive, sessionId: string, onFailure: (failed: boolean) => void) {
  const client = useQueryClient(), submitted = useRef(false)
  const [open, setOpen] = useState(false), [draft, setDraft] = useState<TestDesignContract | null>(null)
  const [editing, setEditing] = useState(false)
  const [decision, setDecision] = useState<'approve' | 'withdraw'>('approve'), [reason, setReason] = useState('')
  const [consent, setConsent] = useState(''), [selected, setSelected] = useState('')
  const m = context.metadata, prefix = ['test-design-scope', m.project_id, m.context_id, sessionId, m.artifact_hash]
  const query = useQuery({ ...sensitive, enabled: open, queryKey: prefix, queryFn: ({ signal }) => testDesignScopeApi.inspect(context, signal) })
  const view = !query.isFetching && !query.isError ? query.data : undefined
  const selectedRevision = view?.history.find((item) => item.revision_id === selected)
  const archive = useQuery({ ...sensitive, enabled: open && !!selectedRevision, queryKey: [...prefix, 'archive', selected],
    queryFn: ({ signal }) => testDesignScopeApi.read(context, selectedRevision!, signal) })
  const failed = query.isError || archive.isError
  useEffect(() => { if (failed) onFailure(true) }, [failed, onFailure])
  const write = useMutation({ retry: false, mutationFn: ({ input, attempt }: { input: ScopeReview; attempt: string }) => testDesignScopeApi.record(input, attempt),
    onSuccess: () => { setDraft(null); setEditing(false); setSelected(''); setReason('') },
    onSettled: () => { setConsent(''); void client.invalidateQueries({ queryKey: ['test-design-scope', m.project_id, m.context_id] }) } })
  const content = view && !archive.isFetching && !archive.isError ? (selected ? archive.data : view.head) : undefined
  const mayApprove = !!view && !view.context_current_use.stale && !!context.context.publication_pin && context.context.required_constraints.length > 0
    && context.context.required_constraints.every((item) => item.oracle && item.authority.status === 'approved')
  const consentKey = JSON.stringify([m, query.dataUpdatedAt, view?.head?.revision.artifact_hash, decision, draft, reason])
  const confirmed = !!view && consent === consentKey
  const canSubmit = editing && !!view?.can_review && !selected && write.isIdle && confirmed && scopeTextValid(reason)
    && (decision === 'withdraw' ? view.head?.revision.status === 'approved' : mayApprove && !!draft && scopeContractValid(draft, context.context))
  const reset = () => { submitted.current = false; setConsent(''); write.reset() }
  return { open, query, archive, view, content, draft, editing, decision, reason, confirmed, canSubmit, mayApprove, write, selected,
    stale: write.error instanceof StaleTestDesignScope,
    toggle: () => { if (!write.isPending) { setOpen(!open); setConsent('') } },
    reload: () => { if (!write.isPending) { reset(); void query.refetch(); if (selected) void archive.refetch() } },
    choose: (id: string) => { setSelected(id); setDraft(null); setEditing(false); setConsent('') },
    begin: (withdraw = false) => { if (!view?.can_review || write.isPending || (withdraw ? view.head?.revision.status !== 'approved' : !mayApprove)) return
      reset(); setSelected(''); setEditing(true); setDecision(withdraw ? 'withdraw' : 'approve'); setReason('')
      setDraft(withdraw ? null : structuredClone(view.head?.request.contract ?? newScopeContract(context.context))) },
    edit: (value: TestDesignContract) => { setConsent(''); setDraft(value) },
    explain: (value: string) => { setConsent(''); setReason(value) },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    submit: () => { if (canSubmit && view && !submitted.current) { submitted.current = true; setConsent('')
      write.mutate({ attempt: crypto.randomUUID(), input: { project_id: m.project_id, context_id: m.context_id, context_artifact_hash: m.artifact_hash,
        expected_previous_revision_id: view.head?.revision.revision_id ?? null, decision, contract: decision === 'approve' ? draft : null,
        reason, policy_revision: 'nasus.test-design-scope.v1' } }) } },
  }
}
