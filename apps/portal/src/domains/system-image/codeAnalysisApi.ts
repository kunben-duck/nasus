import { request } from '../../shared/api/client'
import type { AnalysisPageSelection, CodeAnalysisPage, CodeAnalysisSummary, CodeSourceRevision, CursorPage } from './types/codeAnalysis'

const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/system-image`
const read = <T>(url: string, signal: AbortSignal) => request<T>(url, { signal, cache: 'no-store' })

export const codeAnalysisApi = {
  revisions(projectId: string, afterId: string, signal: AbortSignal) {
    const params = new URLSearchParams({ after_id: afterId, limit: '20' })
    return read<CursorPage<CodeSourceRevision>>(`${root(projectId)}/code-source-revisions?${params}`, signal)
  },
  list(projectId: string, revisionId: string, afterId: string, signal: AbortSignal) {
    const params = new URLSearchParams({ source_revision_id: revisionId, after_id: afterId, limit: '20' })
    return read<CursorPage<CodeAnalysisSummary>>(`${root(projectId)}/source-analyses?${params}`, signal)
  },
  page(projectId: string, revisionId: string, analysisId: string, selection: AnalysisPageSelection, signal: AbortSignal) {
    const params = new URLSearchParams({ source_revision_id: revisionId, section: selection.section,
      offset: String(selection.offset), limit: '25' })
    if (selection.filter) params.set(['files', 'entities'].includes(selection.section) ? 'status' : 'kind', selection.filter)
    return read<CodeAnalysisPage>(`${root(projectId)}/source-analyses/${encodeURIComponent(analysisId)}?${params}`, signal)
  },
}
