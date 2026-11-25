import { request } from '../../shared/api/client'
import type { KnowledgeObject, SourceUploadResult, SystemImageData } from './types'

export const systemImageApi = {
  getKnowledge: (projectId: string) => request<KnowledgeObject[]>(`/v1/projects/${projectId}/knowledge`),
  getSystemImage: (projectId: string, signal?: AbortSignal) =>
    request<SystemImageData>(`/v1/projects/${projectId}/system-image`, { signal }),
  getWorkingImage: (projectId: string, signal?: AbortSignal) =>
    request<SystemImageData>(`/v1/projects/${projectId}/system-image?view=working`, { signal }),
  getKnowledgeDetail: (projectId: string, objectId: string) =>
    request<KnowledgeObject>(`/v1/projects/${projectId}/knowledge/${objectId}`),
  uploadSourceFiles: (
    projectId: string,
    sourceType: SourceUploadResult['source_type'],
    files: File[],
  ) => {
    const payload = new FormData()
    payload.set('source_type', sourceType)
    files.forEach(file => {
      const path = sourceType === 'code' ? file.webkitRelativePath.split('/').slice(1).join('/') : file.name
      if (!path) throw new Error('Choose a code directory')
      payload.append('files', file, path)
    })
    return request<SourceUploadResult>(`/v1/projects/${projectId}/source-files`, {
      method: 'POST',
      body: payload,
    })
  },
}
