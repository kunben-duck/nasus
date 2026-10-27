import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { caseApprovalApi } from './caseApprovalApi'
import { scriptReason } from './automationScriptReviewValidation'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'
import type { CaseAdmissionPreview, CaseAdmissionRequest } from './types/caseApprovals'

export function useCaseApprovals(draft: GenerationArchive, mapping: RecordedMappingArchive, sessionId: string) {
  const [open, setOpen] = useState(false), [editing, setEditing] = useState(false), [decision, setDecision] = useState<'approve' | 'withdraw'>('approve')
  const [reason, setReason] = useState(''), [consent, setConsent] = useState(''), submitted = useRef(false)
  const query = useQuery({ queryKey: ['test-design-case-approvals', draft.metadata.project_id, sessionId,
      mapping.revision.revision_id, mapping.revision.artifact_hash], enabled: open,
    queryFn: ({ signal }) => caseApprovalApi.preview(draft, mapping, signal),
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' })
  const view = !query.isFetching && !query.isError ? query.data : undefined
  const write = useMutation({ retry: false,
    mutationFn: ({ input, preview, attempt }: { input: CaseAdmissionRequest; preview: CaseAdmissionPreview; attempt: string }) => caseApprovalApi.review(input, preview, attempt),
    onSuccess: () => { setEditing(false); setReason('') }, onSettled: () => { setConsent(''); void query.refetch() } })
  const busy = query.isFetching || write.isPending, consentKey = JSON.stringify([query.dataUpdatedAt, view?.basis, view?.head, decision, reason])
  const confirmed = !!view && consent === consentKey
  const mayWithdraw = view?.head?.status === 'approved' && view.head.input_digest === view.basis.input_digest
  const canSubmit = editing && !busy && write.isIdle && confirmed && scriptReason(reason) && view?.can_review
    && (decision === 'approve' ? view.input_current : mayWithdraw)
  return { open, editing, decision, reason, confirmed, busy, view, mayWithdraw, canSubmit, write, failed: query.isError,
    toggle: () => { if (!busy) { setConsent(''); setOpen(!open) } },
    reload: () => { if (!write.isPending) { setConsent(''); setEditing(false); write.reset(); submitted.current = false; void query.refetch() } },
    begin: (withdraw: boolean) => { if (!busy && view?.can_review && (withdraw ? mayWithdraw : view.input_current)) {
      setDecision(withdraw ? 'withdraw' : 'approve'); setEditing(true); setConsent(''); setReason(''); write.reset(); submitted.current = false
    } },
    explain: (text: string) => { setConsent(''); setReason(text) }, confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    submit: () => { if (canSubmit && view && !submitted.current) { submitted.current = true; setConsent(''); write.mutate({ preview: view, attempt: crypto.randomUUID(),
      input: { ...view.selection, expected_input_digest: view.basis.input_digest, expected_previous_revision_id: view.head_revision_id,
        decision, reason, policy_revision: 'nasus.test-design-case-admission.v1' } }) } },
  }
}
