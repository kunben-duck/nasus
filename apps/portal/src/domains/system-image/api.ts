import { request } from '../../shared/api/client'
import type { KnowledgeObject, SourceUploadResult, SystemImageData } from './types'

export const systemImageApi = {
  getKnowledge: (projectId: string) => request<KnowledgeObject[]>(`/v1/projects/${projectId}/knowledge`),
  getSystemImage: (projectId: string) => request<SystemImageData>(`/v1/projects/${projectId}/system-image`),
  getKnowledgeDetail: (projectId: string, objectId: string) =>
    request<KnowledgeObject>(`/v1/projects/${projectId}/knowledge/${objectId}`),
  uploadSourceFiles: (
    projectId: string,
    sourceType: 'us_doc' | 'test_asset',
    files: File[],
  ) => {
    const payload = new FormData()
    payload.set('source_type', sourceType)
    files.forEach((file) => payload.append('files', file, file.name))
    return request<SourceUploadResult>(`/v1/projects/${projectId}/source-files`, {
      method: 'POST',
      body: payload,
    })
  },
}
