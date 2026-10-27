import { request } from '../../shared/api/client'

export interface StructureCommandSummary {
  invocation_id: string
  target_baseline_id: string
  status: 'pending' | 'running' | 'waiting_confirmation' | 'waiting_approval'
  idempotency_key: string | null
}
export interface StructureCommandPage {
  project_id: string
  plan_id: string
  plan_digest: string
  items: StructureCommandSummary[]
  next_after_id: string | null
}

export function validateStructureCommandPage(page: StructureCommandPage, project: string, plan: string, digest: string, cursor: string) {
  if (!page || page.project_id !== project || page.plan_id !== plan || page.plan_digest !== digest
      || !Array.isArray(page.items) || page.items.length > 20
      || (page.next_after_id !== null && (page.items.length !== 20 || page.next_after_id !== page.items.at(-1)?.invocation_id))) {
    throw new Error('Structural discovery scope mismatch')
  }
  let previous = cursor
  for (const item of page.items) {
    if (!item || typeof item.invocation_id !== 'string' || item.invocation_id <= previous || item.invocation_id.length > 128
        || typeof item.target_baseline_id !== 'string' || !item.target_baseline_id || item.target_baseline_id.length > 128
        || !['pending', 'running', 'waiting_confirmation', 'waiting_approval'].includes(item.status)
        || (item.idempotency_key !== null && (typeof item.idempotency_key !== 'string' || !item.idempotency_key || item.idempotency_key.length > 128))) {
      throw new Error('Structural discovery page is invalid')
    }
    previous = item.invocation_id
  }
  return page
}

export const structureCommandDiscoveryApi = {
  async list(project: string, plan: string, digest: string, cursor: string, signal?: AbortSignal) {
    const url = `/v1/projects/${encodeURIComponent(project)}/system-image/build-plans/${encodeURIComponent(plan)}/structure-commands`
    const page = await request<StructureCommandPage>(`${url}?${new URLSearchParams({ plan_digest: digest, after_id: cursor, limit: '20' })}`,
      { signal, cache: 'no-store' })
    return validateStructureCommandPage(page, project, plan, digest, cursor)
  },
}
