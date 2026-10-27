import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ContextArchive } from '../system-image/types/contextPack'
import { verifyScopeArchive, verifyScopeView } from './testDesignScopeValidation'
import type { ScopeArchive, ScopeReview, ScopeRevision, ScopeView } from './types/testDesignScope'

const root = (project: string) => `/v1/projects/${encodeURIComponent(project)}/quality/test-design-scopes`
export class StaleTestDesignScope extends Error {}
export const testDesignScopeApi = {
  async inspect(context: ContextArchive, signal: AbortSignal) {
    const m = context.metadata
    return verifyScopeView(await request<ScopeView>(`${root(m.project_id)}?${new URLSearchParams({ context_id: m.context_id })}`,
      { signal, cache: 'no-store' }), context)
  },
  async read(context: ContextArchive, revision: ScopeRevision, signal: AbortSignal) {
    return verifyScopeArchive(await request<ScopeArchive>(`${root(context.metadata.project_id)}/${encodeURIComponent(revision.revision_id)}`,
      { signal, cache: 'no-store' }), context, revision)
  },
  async record(input: ScopeReview, attempt: string) {
    const pending = await platformApi.invokeTool({ tool_id: 'quality.test_design_scope.review', input: { ...input }, idempotency_key: attempt })
    if (pending.status !== 'waiting_confirmation') throw new Error('Explicit scope confirmation required')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.result?.followup_reason === 'test_design_scope_changed') throw new StaleTestDesignScope('Scope inputs changed')
    if (done.status !== 'completed' || !done.result?.object_refs.some((ref) => ref.startsWith('test_design_scope:'))) throw new Error('Scope review not acknowledged')
    return done.id
  },
}
