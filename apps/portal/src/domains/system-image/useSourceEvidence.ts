import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { evidenceApi } from './evidenceApi'
import type { SourceEvidence } from './types/evidence'
import type { KnowledgeCodeReference } from './types/knowledge'

// Source text is fetched on opening, never persisted in the application cache.
const sensitiveRead = { staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: 'always' as const }

export function useSourceEvidence(projectId: string, reference: KnowledgeCodeReference | null | undefined, objectId: string) {
  return useQuery({
    ...sensitiveRead,
    queryKey: ['source-evidence', projectId, reference?.source_revision_id, reference?.entity_revision_id, objectId],
    queryFn: ({ signal }) => evidenceApi.list(projectId, reference!, objectId, signal),
    enabled: Boolean(reference),
  })
}

export function useSourceEvidencePages(projectId: string, evidence: SourceEvidence) {
  return useInfiniteQuery({
    ...sensitiveRead,
    queryKey: ['source-evidence-pages', projectId, evidence.evidence_id],
    queryFn: ({ pageParam, signal }) => evidenceApi.read(projectId, evidence.evidence_id, pageParam, signal),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => lastPage.next_start_line ?? undefined,
    enabled: evidence.locator.precision === 'exact',
  })
}
