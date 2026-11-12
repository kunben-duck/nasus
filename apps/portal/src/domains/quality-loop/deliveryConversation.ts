import type { ConversationSession } from '../agent/types'
import type { IterationImageBinding } from './types/delivery'
import { deliveryId, validIterationBinding } from './iterationCreation'

export interface DeliveryIntake {
  schema_version: 'nasus.delivery-dialogue.v1'
  project_id: string
  proposal_id: string
  name: string
  publication_id?: string | null
  image_binding?: IterationImageBinding | null
  stage: 'selection' | 'confirmation' | 'created'
  version_id?: string | null
}

export function deliveryConversationState(conversation: ConversationSession) {
  const messages = conversation.messages.filter((message) => message.role === 'assistant')
  const proposalIndex = messages.findLastIndex((message) => message.metadata?.delivery_intake)
  const observationIndex = messages.findLastIndex((message) => message.metadata?.version_delivery)
  const raw = messages[proposalIndex]?.metadata?.delivery_intake as DeliveryIntake | undefined
  const proposal = raw?.schema_version === 'nasus.delivery-dialogue.v1' && raw.project_id === conversation.project_id
    && deliveryId(raw.proposal_id) && typeof raw.name === 'string' && ['selection', 'confirmation', 'created'].includes(raw.stage)
    && (!raw.image_binding || validIterationBinding(raw.image_binding))
    && (raw.stage === 'selection' || (raw.name.trim().length > 0 && validIterationBinding(raw.image_binding) && raw.publication_id === raw.image_binding.publication_id))
    && (raw.stage !== 'created' || deliveryId(raw.version_id)) ? raw : undefined
  const observation = messages[observationIndex]?.metadata?.version_delivery as
    { project_id?: unknown; version_id?: unknown } | undefined
  // Conversation observations are navigation hints, never current delivery evidence.
  const versionId = observationIndex >= proposalIndex && observation && observation.project_id === conversation.project_id && deliveryId(observation.version_id) ? observation.version_id
    : proposal?.stage === 'created' ? proposal.version_id! : undefined
  return { proposal, versionId }
}
