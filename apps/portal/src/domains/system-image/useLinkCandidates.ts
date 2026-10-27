import { useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { linkCandidateApi, type LinkRelation } from './linkCandidateApi'
import type { ImageObjectMember } from './types/imageRevision'
import type { ImageReadScope } from './useImageRevisions'

export function useLinkCandidates(scope: ImageReadScope, revision: string, target: ImageObjectMember) {
  const mutation = useMutation({ mutationFn: ({ relation, limit = 30 }: { relation: LinkRelation; limit?: number }) =>
    linkCandidateApi.recall(scope.projectId, revision, target.object_id, relation, limit),
  })
  const selection = mutation.data
  const query = useQuery({
    queryKey: ['system-image-link-candidates', scope.projectId, scope.sessionId, revision, target.document_revision_id, selection],
    queryFn: ({ signal }) => linkCandidateApi.expand(scope.projectId, revision, target, selection!, signal),
    enabled: !!selection && !mutation.isPending && !mutation.isError,
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always',
  })
  const { onFailure } = scope
  useEffect(() => { if (mutation.isError || query.isError) onFailure(true) }, [mutation.isError, query.isError, onFailure])
  return { mutation, query }
}
