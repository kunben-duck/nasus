import { systemImageApi } from './api'
import type { SourceUploadResult } from './types'

export type UploadableSystemImageSourceType = 'us_doc' | 'test_asset'

export function uploadSystemImageSourceFiles(
  projectId: string,
  sourceType: UploadableSystemImageSourceType,
  files: File[],
): Promise<SourceUploadResult> {
  return systemImageApi.uploadSourceFiles(projectId, sourceType, files)
}
