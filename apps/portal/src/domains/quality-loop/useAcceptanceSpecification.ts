import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { acceptanceSpecificationApi, oracleKeys, StaleAcceptanceAuthority, type AcceptanceSelection, type AcceptanceView, type ObservableOracle, type AuthorityKind } from './acceptanceSpecificationApi'

export function useAcceptanceSpecification(selection: AcceptanceSelection, evidenceIds: string[], sessionId: string, onFailure: (failed: boolean) => void, kind: AuthorityKind = 'acceptance_criterion') {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [decision, setDecision] = useState<'approve' | 'withdraw'>('approve')
  const [oracle, setOracle] = useState<ObservableOracle>({ preconditions: '', action: '', observation: '', expected_result: '' })
  const [reason, setReason] = useState('')
  const [consent, setConsent] = useState('')
  const submitted = useRef(false)
  const key = [kind === 'business_rule' ? 'business-rule' : 'acceptance-specification', selection.project_id, sessionId, selection.image_revision_id, selection.object_id]
  const query = useQuery({ queryKey: key, enabled: open, queryFn: ({ signal }) => acceptanceSpecificationApi.inspect(selection, evidenceIds, signal, kind),
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' })
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  const write = useMutation({ retry: false, mutationFn: (input: { view: AcceptanceView; decision: 'approve' | 'withdraw'; oracle: ObservableOracle; reason: string; attempt: string }) =>
    acceptanceSpecificationApi.record(input.view, input.decision, input.oracle, input.reason, input.attempt, kind),
    onSettled: () => { setConsent(''); void client.invalidateQueries({ queryKey: key }) } })
  const view = query.isFetching || query.isError ? undefined : query.data
  const consentKey = JSON.stringify([view?.basis_digest, view?.head?.revision_id, query.dataUpdatedAt, decision, oracle, reason])
  const confirmed = consent === consentKey
  const canSubmit = !!view?.can_review && confirmed && write.isIdle && !!reason.trim() && reason.length <= 2000
    && (decision === 'approve' ? oracleKeys.every((field) => !!oracle[field].trim() && oracle[field].length <= 2000) : view.head?.status === 'approved')
  return { open, query, view, decision, oracle, reason, confirmed, canSubmit, write, stale: write.error instanceof StaleAcceptanceAuthority,
    toggle: () => { setConsent(''); setOpen(!open) },
    choose: (value: 'approve' | 'withdraw') => { setConsent(''); setDecision(value) },
    edit: (field: keyof ObservableOracle, value: string) => { setConsent(''); setOracle({ ...oracle, [field]: value }) },
    explain: (value: string) => { setConsent(''); setReason(value) },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    reload: () => { if (!write.isPending) { submitted.current = false; setConsent(''); write.reset(); void query.refetch() } },
    submit: () => { if (canSubmit && view && !submitted.current) { submitted.current = true; setConsent('');
      write.mutate({ view, decision, oracle, reason, attempt: crypto.randomUUID() }) } },
  }
}
