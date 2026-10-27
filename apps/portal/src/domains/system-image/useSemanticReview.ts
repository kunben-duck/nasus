import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { semanticReviewApi, StaleSemanticReview } from './semanticReviewApi'
import type { ImageReadScope } from './useImageRevisions'
import type { SemanticJudgment, SemanticResult } from './types/semanticEvaluation'
import type { SemanticReviewChoice, SemanticReviewPage } from './types/semanticReview'

export function useSemanticReview(scope: ImageReadScope, result: SemanticResult, subject: SemanticJudgment) {
  const client = useQueryClient()
  const [offsets, setOffsets] = useState([0])
  const [head, setHead] = useState<string | undefined>()
  const [decision, setDecision] = useState<SemanticReviewChoice>('defer')
  const [reason, setReason] = useState('')
  const [consent, setConsent] = useState('')
  const submitted = useRef(false)
  const key = ['semantic-reviews', scope.projectId, scope.sessionId, result.invocation_id, subject.subject_object_id]
  const query = useQuery({ queryKey: [...key, offsets.at(-1), head],
    queryFn: ({ signal }) => semanticReviewApi.history(result, subject, offsets.at(-1)!, signal, head),
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' })
  const { onFailure } = scope
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  const write = useMutation({ retry: false,
    mutationFn: ({ page, attempt, choice, explanation }: { page: SemanticReviewPage; attempt: string; choice: SemanticReviewChoice; explanation: string }) =>
      semanticReviewApi.record(page, choice, explanation, attempt),
    onSettled: () => { setConsent(''); setOffsets([0]); setHead(undefined); void client.invalidateQueries({ queryKey: ['semantic-reviews', scope.projectId, scope.sessionId] }) },
  })
  const page = query.isFetching || query.isError ? undefined : query.data
  const consentKey = JSON.stringify([result.invocation_id, subject.subject_object_id, page?.assertion.assertion_digest,
    page?.head_decision_id, query.dataUpdatedAt, decision, reason])
  const confirmed = consent === consentKey
  const canSubmit = !!page && write.isIdle && !!reason.trim() && reason.length <= 2000
    && (decision !== 'accept' || page.assertion.can_accept) && confirmed
  function change() { setConsent('') }
  return { query, page, decision, reason, confirmed, write, canSubmit, stale: write.error instanceof StaleSemanticReview,
    choose: (value: SemanticReviewChoice) => { if (!write.isPending) { setDecision(value); change() } },
    explain: (value: string) => { if (!write.isPending) { setReason(value); change() } },
    confirm: (checked: boolean) => setConsent(checked ? consentKey : ''),
    submit: () => { if (canSubmit && page && !submitted.current) { submitted.current = true; setConsent('');
      write.mutate({ page, attempt: crypto.randomUUID(), choice: decision, explanation: reason }) } },
    reload: () => { if (!write.isPending) { submitted.current = false; write.reset(); change(); setOffsets([0]); setHead(undefined); void client.invalidateQueries({ queryKey: key }) } },
    pageNumber: offsets.length,
    previous: offsets.length > 1 && !write.isPending ? () => { change(); setOffsets(offsets.slice(0, -1)) } : undefined,
    next: page?.next_offset != null && !write.isPending ? () => { change(); setHead(page.head_decision_id ?? ''); setOffsets([...offsets, page.next_offset!]) } : undefined,
  }
}
