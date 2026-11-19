import { request } from '../../shared/api/client'
import { requirementReviewsApi } from './requirementReviews'
import { testDesignReviewApi } from './testDesignReviewApi'
import type { GenerationArchive, PlannedCase } from './types/testDesignGeneration'
import { caseRevisionRequest, verifySavedCaseRevision } from './caseRevisionValidation'

export async function reviseCases(actorId: string, draft: GenerationArchive, cases: PlannedCase[], reason: string) {
  const projectId = draft.metadata.project_id
  const input = caseRevisionRequest(draft, cases, reason)
  const done = await requirementReviewsApi.execute(actorId, 'quality.test_design.cases.revise', input)
  const id = done.result?.object_refs.find((ref) => ref.startsWith('test_design_result:'))?.slice('test_design_result:'.length)
  if (!id) throw new Error('Case revision receipt missing')
  const value = await request<GenerationArchive>(`/v1/projects/${encodeURIComponent(projectId)}/quality/test-design-results/${encodeURIComponent(id)}`, { cache: 'no-store' })
  const archive = await testDesignReviewApi.draft(projectId, { metadata: value.metadata, context_pin: value.result.context_pin,
    scope_pin: value.result.scope_pin }, new AbortController().signal)
  return verifySavedCaseRevision(archive, draft, input, actorId, done.id)
}
