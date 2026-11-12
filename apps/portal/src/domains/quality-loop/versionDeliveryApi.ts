import { request } from '../../shared/api/client'
import type { VersionDelivery } from './types/delivery'
import type { VersionSummary } from './types/version'
import { deliveryId } from './iterationCreation'
import { verifyVersionDelivery } from './versionDeliveryValidation'

const root = (projectId: string) => `/v1/projects/${encodeURIComponent(projectId)}/versions`
export const versionDeliveryApi = {
  async list(projectId: string, signal: AbortSignal) {
    const value = await request<VersionSummary[]>(root(projectId), { signal, cache: 'no-store' })
    signal.throwIfAborted()
    if (!Array.isArray(value) || value.some((item) => !deliveryId(item.id) || typeof item.name !== 'string')
        || new Set(value.map((item) => item.id)).size !== value.length) throw new Error('Iteration list mismatch')
    return value
  },
  async read(projectId: string, versionId: string, signal: AbortSignal) {
    if (!deliveryId(projectId) || !deliveryId(versionId)) throw new Error('Select an explicit iteration')
    const value = await request<VersionDelivery>(`${root(projectId)}/${encodeURIComponent(versionId)}/delivery`, { signal, cache: 'no-store' })
    signal.throwIfAborted()
    return verifyVersionDelivery(value, projectId, versionId)
  },
}
