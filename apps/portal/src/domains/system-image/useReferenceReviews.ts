import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { referenceReviewApi } from './referenceReviewApi'
import { imageRevisionApi } from './imageRevisionApi'
import type { ImageReadScope } from './useImageRevisions'
import type { ReferenceReadPin } from './referencePageRead'

function useScopedRead<T>(scope: ImageReadScope, key: readonly unknown[], read: (signal: AbortSignal) => Promise<T>) {
  const query = useQuery({ queryKey: ['system-image-link-reviews', scope.projectId, scope.sessionId, ...key],
    queryFn: ({ signal }) => read(signal), gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
  })
  const { onFailure } = scope
  useEffect(() => { if (query.isError) onFailure(true) }, [query.isError, onFailure])
  return query
}
export function useReferenceProposals(scope: ImageReadScope, revision: string, cursor: string) {
  return useScopedRead(scope, ['proposals', revision, cursor], (signal) => referenceReviewApi.list(scope.projectId, revision, cursor, signal))
}
export function useReferencePage(scope: ImageReadScope, revision: string, proposal: string, section: 'assertions' | 'gaps', offset: number, pin: ReferenceReadPin) {
  return useScopedRead(scope, ['proposal', revision, proposal, section, offset, pin.imageArtifactHash, pin.proposalDigest],
    (signal) => referenceReviewApi.page(scope.projectId, revision, proposal, section, offset, signal, pin))
}
export function useReferenceHistory(scope: ImageReadScope, revision: string, proposal: string, assertion: string, offset: number, proposalDigest: string) {
  return useScopedRead(scope, ['decisions', revision, proposal, assertion, offset, proposalDigest],
    (signal) => referenceReviewApi.history(scope.projectId, revision, proposal, assertion, offset, signal, proposalDigest))
}

export function useReferenceEvidence(scope: ImageReadScope, revision: string, object: string, evidence: string, start?: number) {
  return useScopedRead(scope, ['evidence', revision, object, evidence, start], async (signal) => {
    const page = await imageRevisionApi.evidence(scope.projectId, revision, object, evidence, start, signal)
    if (page.evidence.evidence_id !== evidence || page.integrity !== 'verified') throw new Error('Reference evidence mismatch')
    return page
  })
}
