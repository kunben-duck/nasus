import { request } from '../../shared/api/client'
import type { SourceEvidencePage } from './types/evidence'
import type { SourceDocumentPage } from './types/sourceDocument'
import type { ImagePageSelection, ImageRevisionList, ImageRevisionPage } from './types/imageRevision'

const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/system-image/revisions`
const read = <T>(url: string, signal: AbortSignal) => request<T>(url, { signal, cache: 'no-store' })

export const imageRevisionApi = {
  document(projectId: string, revisionId: string, objectId: string, offset: number, signal: AbortSignal) {
    const path = `${root(projectId)}/${encodeURIComponent(revisionId)}/objects/${encodeURIComponent(objectId)}/document`
    return read<SourceDocumentPage>(`${path}?offset=${offset}&limit=10`, signal)
  },
  async list(projectId: string, cursor: string, signal: AbortSignal) {
    const params = new URLSearchParams({ limit: '20', after_id: cursor })
    const list = await read<ImageRevisionList>(`${root(projectId)}?${params}`, signal)
    if (list.items.some((item) => item.project_id !== projectId)) throw new Error('Image revision scope mismatch')
    return list
  },
  async page(projectId: string, revisionId: string, selection: ImagePageSelection, signal: AbortSignal, limit = 25) {
    const params = new URLSearchParams({ section: selection.section, offset: String(selection.offset), limit: String(limit) })
    const page = await read<ImageRevisionPage>(`${root(projectId)}/${encodeURIComponent(revisionId)}?${params}`, signal)
    if (page.revision.project_id !== projectId || page.revision.image_revision_id !== revisionId || page.section !== selection.section) {
      throw new Error('Image revision scope mismatch')
    }
    const end = selection.offset + page.items.length
    if (!Number.isSafeInteger(page.total) || page.total < end || page.items.length > limit
      || (page.items.length === 0 && selection.offset !== page.total)
      || page.next_offset !== (end < page.total ? end : null)) {
      throw new Error('Frozen image pagination mismatch')
    }
    if (page.section === 'semantic_assertion_members') {
      if (page.items.length > 0 && page.revision.policy_version !== 'nasus.image-candidate.v3') throw new Error('Invalid semantic image policy')
      for (const { assertion: a, decision: d } of page.items) {
        if (a.project_id !== projectId || d.project_id !== projectId || d.image_revision_id !== a.image_revision_id
          || d.evaluation_id !== a.evaluation_id || d.evidence_digest !== a.evidence_digest
          || !/^sha256:[0-9a-f]{64}$/.test(d.assertion_digest) || d.assertion_id !== `sa_${d.assertion_digest.slice(7)}`
          || !/^sc_[0-9a-f]{64}$/.test(d.claim_id) || !d.decision_id || !d.reason.trim()
          || !['accept', 'reject', 'defer'].includes(d.decision) || !['implements', 'asserts'].includes(a.predicate)
          || a.authority_status !== 'pending_confirmation' || a.semantic_kind !== 'inferred' || a.status !== 'proposed'
          || d.policy_revision !== 'nasus.semantic-link-review.v1' || a.applicability !== 'selected_image_only_not_verified_coverage'
          || d.applicability !== a.applicability || (d.decision === 'accept' && (a.assessment !== 'supports' || (a.predicate === 'asserts' && !a.oracle_digest)))) {
          throw new Error('Frozen semantic review mismatch')
        }
      }
    }
    return page
  },
  evidence(projectId: string, revisionId: string, objectId: string, evidenceId: string, startLine: number | undefined, signal: AbortSignal) {
    const params = new URLSearchParams({ max_lines: '100' })
    if (startLine !== undefined) params.set('start_line', String(startLine))
    const path = `${root(projectId)}/${encodeURIComponent(revisionId)}/objects/${encodeURIComponent(objectId)}/evidence/${encodeURIComponent(evidenceId)}`
    return read<SourceEvidencePage>(`${path}?${params}`, signal)
  },
}
