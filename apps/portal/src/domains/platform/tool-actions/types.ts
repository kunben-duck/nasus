export type StudioActionId =
  | 'system-image.build-goal'
  | 'system-image.register-sources'
  | 'system-image.ingest-sources'
  | 'system-image.materialize-context'
  | 'system-image.initialize-baseline'
  | 'system-image.status'
  | 'quality-loop.continue-goal'
  | 'release.assess'

export type StudioActionSurface = 'chat' | 'ui' | 'api' | 'agent_loop'

export type StudioSourceBindingValues = {
  code: string
  usDoc: string
  testAsset: string
}

export type StudioActionContext = {
  projectId: string
  projectName?: string
  input?: Record<string, unknown>
}

export type ConversationActionCommand = {
  kind: 'conversation_message'
  actionId: 'system-image.build-goal' | 'quality-loop.continue-goal'
  content: string
}

export type ToolActionCommand = {
  kind: 'tool_invocation'
  actionId: StudioActionId
  tool_id: string
  input: Record<string, unknown>
  initiator_surface: StudioActionSurface
  initiator_actor: 'user' | 'agent'
  target_scope: 'central'
}

export type StudioActionCommand = ConversationActionCommand | ToolActionCommand
