import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import { contextRegistrationId as id, verifyContextAuthorityBackfillPage } from './contextAuthorityRegistrationValidation'
import type { ContextAuthorityBackfillItem, ContextAuthorityRegistrationRequest } from './contextAuthorityRegistrationValidation'

const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/system-image/context-authority-backfill`
export const contextAuthorityRegistrationApi = {
  async page(projectId: string, afterId: string, signal?: AbortSignal) {
    const params = new URLSearchParams({ after_id: afterId, limit: '3' })
    const value = await request<unknown>(`${root(projectId)}?${params}`, { signal, cache: 'no-store' })
    signal?.throwIfAborted()
    return verifyContextAuthorityBackfillPage(value, projectId, afterId)
  },
  async register(selected: ContextAuthorityBackfillItem, afterId: string, attempt: string) {
    const input = selected.registration_request
    // Recheck the original page before creating a new confirmed command.
    const page = await this.page(input.project_id, afterId)
    const fresh = page.items.find((item) => item.registration_request.context_id === input.context_id)
    if (!fresh || Object.entries(input).some(([key, value]) => fresh.registration_request[key as keyof ContextAuthorityRegistrationRequest] !== value)
      || fresh.image_revision_id !== selected.image_revision_id || fresh.image_artifact_hash !== selected.image_artifact_hash) {
      throw new Error('Historical dependency selection changed; reload before confirming again')
    }
    const toolId = 'system_image.context.register_authorities'
    const pending = await platformApi.invokeTool({ tool_id: toolId, idempotency_key: attempt, input: { ...input } })
    if (pending.tool_id !== toolId || pending.status !== 'waiting_confirmation' || !id(pending.id)
      || Object.entries(input).some(([key, value]) => pending.input_payload[key] !== value)) throw new Error('Independent registration confirmation was not acknowledged')
    const done = await platformApi.confirmToolInvocation(pending.id)
    if (done.id !== pending.id || done.tool_id !== toolId || done.status !== 'completed' || done.result?.status !== 'completed'
      || done.result.invocation_id !== pending.id || done.result.object_refs.length !== 1
      || done.result.object_refs[0] !== `context_pack:${input.context_id}`) throw new Error('Historical dependency registration was not acknowledged')
    return input.context_id
  },
}
