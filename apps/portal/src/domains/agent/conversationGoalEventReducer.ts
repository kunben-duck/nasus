import type { EventPayload } from '../platform/types'
import type { ConversationSession } from './types'
import { asAgentStep } from './eventPayloadReaders'
import { upsertById } from '../../shared/event-reducer/eventUpsert'

export function reduceAgentStepEvent(conversation: ConversationSession, event: EventPayload): ConversationSession {
  const step = asAgentStep(event.patch.agent_step)
  const goalId = event.agent_goal_id
  if (!step || !goalId) return conversation
  const currentGoal = (conversation.agent_goals ?? []).find((goal) => goal.id === goalId)
  if (!currentGoal) return conversation
  const currentStep = currentGoal.steps.find((item) => item.id === step.id)
  const field = event.event_type === 'agent.step.thinking.delta' ? 'reasoning'
    : event.event_type === 'agent.step.observation.delta' ? 'observation_summary'
      : event.event_type === 'agent.step.decision.delta' ? 'decision_rationale' : undefined
  if (!currentStep || !field) return conversation
  const nextText = step[field]
  const currentText = currentStep[field] ?? ''
  if (typeof nextText !== 'string' || nextText === currentText || !nextText.startsWith(currentText)) return conversation
  return {
    ...conversation,
    agent_goals: upsertById(conversation.agent_goals ?? [], {
      ...currentGoal,
      // Delta text is presentation; status, command pins and consent belong
      // to the fresh checkpoint, not historical step events.
      steps: upsertById(currentGoal.steps, { ...currentStep, [field]: nextText }),
    }),
  }
}
