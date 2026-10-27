import { request } from '../../shared/api/client'
import { compareMappingIds } from './testDesignMappingPartitions'
import { verifyAutomationInput } from './automationInputValidation'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'

function requireValue(value: unknown): asserts value { if (!value) throw new Error('Fixed automation input could not be verified') }

export async function readAutomationInput(draft: GenerationArchive, mapping: RecordedMappingArchive, signal: AbortSignal) {
  signal.throwIfAborted()
  const ids = mapping.assessment?.accepted_case_ids ?? []
  requireValue(ids.length > 0 && ids.length <= 512 && new Set(ids).size === ids.length
    && draft.current_use.scope_current && mapping.current_use.scope_current && mapping.current_use.mapping_current
    && mapping.current_use.mapping_complete && mapping.revision.status === 'reviewed')
  const query = new URLSearchParams({ artifact_hash: mapping.revision.artifact_hash })
  for (const id of [...ids].sort(compareMappingIds)) query.append('case_ids', id)
  const value = await request<unknown>(`/v1/projects/${encodeURIComponent(draft.metadata.project_id)}/quality/test-design-mapping-reviews/${encodeURIComponent(mapping.revision.revision_id)}/automation-input-preview?${query}`,
    { cache: 'no-store', signal })
  const result = await verifyAutomationInput(value, draft, mapping)
  signal.throwIfAborted()
  return result
}
