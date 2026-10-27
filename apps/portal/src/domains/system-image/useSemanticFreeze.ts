import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { semanticMembershipApi } from './semanticMembershipApi'
import { StaleSemanticReview } from './semanticReviewApi'
import type { SemanticReviewPage } from './types/semanticReview'

export function useSemanticFreeze(page: SemanticReviewPage) {
  const client = useQueryClient()
  const [confirmed, setConfirmed] = useState(false)
  const submitted = useRef(false)
  const write = useMutation({ retry: false,
    mutationFn: ({ snapshot, attempt }: { snapshot: SemanticReviewPage; attempt: string }) => semanticMembershipApi.freeze(snapshot, attempt),
    // Refetching the enclosing selector here would unmount the receipt. The
    // explicit reload/reopen reauthorizes and fetches the new candidate list.
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['system-image', page.assertion.project_id, 'image-revisions'], refetchType: 'none' }) },
    onSettled: () => setConfirmed(false),
  })
  return { write, confirmed, confirm: setConfirmed, stale: write.error instanceof StaleSemanticReview,
    canSubmit: confirmed && !!page.head && write.isIdle,
    submit: () => { if (confirmed && page.head && write.isIdle && !submitted.current) {
      submitted.current = true
      write.mutate({ snapshot: page, attempt: crypto.randomUUID() })
    } },
  }
}
