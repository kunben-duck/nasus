import { request } from '../../shared/api/client'
import type { SourceEvidence, SourceEvidencePage } from './types/evidence'
import type { KnowledgeCodeReference } from './types/knowledge'

function evidencePath(projectId: string) {
  return `/v1/projects/${encodeURIComponent(projectId)}/system-image/evidence`
}

export const evidenceApi = {
  list: (projectId: string, reference: KnowledgeCodeReference, objectId: string, signal?: AbortSignal) => {
    const query = new URLSearchParams({ source_revision_id: reference.source_revision_id,
      entity_revision_id: reference.entity_revision_id, object_id: objectId })
    return request<SourceEvidence[]>(`${evidencePath(projectId)}?${query}`, { signal, cache: 'no-store' })
  },
  read: (projectId: string, evidenceId: string, startLine?: number, signal?: AbortSignal) => {
    const query = new URLSearchParams({ max_lines: '100' })
    if (startLine !== undefined) query.set('start_line', String(startLine))
    return request<SourceEvidencePage>(`${evidencePath(projectId)}/${encodeURIComponent(evidenceId)}?${query}`, {
      signal, cache: 'no-store',
    })
  },
}
