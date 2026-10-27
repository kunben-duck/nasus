import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { imageRevisionApi } from './imageRevisionApi'
import { loadImageRevisionPage } from './imageRevisionPage'
import { imagePagePlaceholder } from './imagePageReuse'
import type { ImageObjectMember, ImagePageSelection } from './types/imageRevision'

const sensitiveRead = { staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }
export interface ImageReadScope { projectId: string; sessionId: string; onFailure: (failed: boolean) => void }
function useFailure(isError: boolean, scope: ImageReadScope) {
  const { onFailure } = scope
  useEffect(() => { if (isError) onFailure(true) }, [isError, onFailure])
}

export function useImageRevisions(scope: ImageReadScope, cursor: string) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image', scope.projectId, 'image-revisions', scope.sessionId, cursor],
    queryFn: ({ signal }) => imageRevisionApi.list(scope.projectId, cursor, signal),
  })
  useFailure(query.isError, scope)
  return query
}

export function useImageRevisionPage(scope: ImageReadScope, revisionId: string, selection: ImagePageSelection) {
  const queryKey = ['system-image', scope.projectId, 'image-page', scope.sessionId, revisionId, selection] as const
  const query = useQuery({ ...sensitiveRead,
    queryKey,
    queryFn: ({ signal }) => loadImageRevisionPage(scope.projectId, revisionId, selection, signal),
    // Keep image-level panels mounted, but the view hides all old records while
    // the new page is verified. Never retain data across a private read scope.
    placeholderData: (previous, previousQuery) => imagePagePlaceholder(previous, previousQuery?.queryKey, queryKey),
  })
  useFailure(query.isError, scope)
  return query
}

export function useImageEvidence(scope: ImageReadScope, revisionId: string, member: ImageObjectMember, evidenceId: string, startLine?: number) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image', scope.projectId, 'image-evidence', scope.sessionId, revisionId, member.object_id, evidenceId, startLine],
    queryFn: async ({ signal }) => {
      if (!member.evidence_ids.includes(evidenceId)) throw new Error('Evidence is not frozen in this object')
      const page = await imageRevisionApi.evidence(scope.projectId, revisionId, member.object_id, evidenceId, startLine, signal)
      if (page.evidence.evidence_id !== evidenceId || page.evidence.source_revision_id !== member.source_revision_id || page.integrity !== 'verified') {
        throw new Error('Frozen evidence scope mismatch')
      }
      return page
    },
  })
  useFailure(query.isError, scope)
  return query
}

export function useImageDocument(scope: ImageReadScope, revisionId: string, member: ImageObjectMember, offset: number) {
  const query = useQuery({ ...sensitiveRead,
    queryKey: ['system-image', scope.projectId, 'image-document', scope.sessionId, revisionId, member.object_id, offset],
    queryFn: async ({ signal }) => {
      const page = await imageRevisionApi.document(scope.projectId, revisionId, member.object_id, offset, signal)
      if (page.document.project_id !== scope.projectId || page.document.document_revision_id !== member.document_revision_id
          || page.document.source_revision_id !== member.source_revision_id) throw new Error('Frozen document scope mismatch')
      return page
    },
  })
  useFailure(query.isError, scope)
  return query
}
