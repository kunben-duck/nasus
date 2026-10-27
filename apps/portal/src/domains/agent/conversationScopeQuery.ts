import { agentApi } from './api'
import type { SpaceType } from '../platform/types'
import { requireActiveQueryScope } from '../../shared/api/queryScope'

export async function readConversationScope(spaceType: SpaceType, spaceId: string, title: string,
  existingOnly: boolean, signal: AbortSignal, canReadWorkspace?: () => boolean) {
  if (!existingOnly) {
    requireActiveQueryScope(canReadWorkspace, signal)
    const conversation = await agentApi.ensureConversation(spaceType, spaceId, title, signal)
    requireActiveQueryScope(canReadWorkspace, signal)
    return conversation
  }
  if (spaceType !== 'project') throw new Error('Read-only discovery requires a project scope')
  return agentApi.readProjectConversation(spaceId, signal)
}
