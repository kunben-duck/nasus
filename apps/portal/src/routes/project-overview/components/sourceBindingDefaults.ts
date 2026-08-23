import type { StudioSourceBindingValues } from '../../../domains/platform/tool-actions'
import type { SystemImageData } from '../../../domains/system-image/types'

export type SourceBindingValues = StudioSourceBindingValues

export function sourceBindingDefaults(systemImage?: SystemImageData): SourceBindingValues {
  const sourceFor = (sourceType: 'code' | 'us_doc' | 'test_asset') => {
    const source = systemImage?.sources.find((item) => item.source_type === sourceType)
    if (!source) return ''
    if (source.content_hash || source.evidence_refs.length || source.ingestion_status !== 'pending') {
      return source.source_uri
    }
    return ''
  }

  return {
    code: sourceFor('code'),
    usDoc: sourceFor('us_doc'),
    testAsset: sourceFor('test_asset'),
  }
}
