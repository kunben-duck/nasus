import { systemImageApi } from './api'
import type { SourceUploadResult } from './types'

export type UploadableSystemImageSourceType = SourceUploadResult['source_type']

export function uploadSystemImageSourceFiles(
  projectId: string,
  sourceType: UploadableSystemImageSourceType,
  files: File[],
): Promise<SourceUploadResult> {
  return systemImageApi.uploadSourceFiles(projectId, sourceType, files)
}
