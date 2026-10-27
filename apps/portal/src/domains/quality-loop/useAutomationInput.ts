import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { readAutomationInput } from './automationInputApi'
import type { GenerationArchive } from './types/testDesignGeneration'
import type { RecordedMappingArchive } from './types/testDesignMapping'

export function useAutomationInput(draft: GenerationArchive, mapping: RecordedMappingArchive, sessionId: string) {
  const [open, setOpen] = useState(false)
  const available = draft.current_use.scope_current && mapping.current_use.mapping_current && mapping.current_use.mapping_complete
    && !!mapping.assessment?.accepted_case_ids.length && mapping.assessment.accepted_case_ids.length <= 512
  const query = useQuery({ queryKey: ['automation-input', draft.metadata.project_id, sessionId,
      draft.metadata.generation_id, draft.metadata.artifact_hash, mapping.revision.revision_id, mapping.revision.artifact_hash],
    queryFn: ({ signal }) => readAutomationInput(draft, mapping, signal), enabled: open && available,
    gcTime: 0, staleTime: 0, retry: false, refetchOnWindowFocus: 'always' })
  return { open, available, busy: query.isFetching, failed: query.isError,
    value: available && !query.isFetching && !query.isError ? query.data : undefined,
    toggle: () => setOpen(!open), reload: () => { if (available && !query.isFetching) void query.refetch() } }
}
