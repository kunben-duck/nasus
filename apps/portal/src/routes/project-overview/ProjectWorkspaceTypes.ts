export type AgentMode = 'planning' | 'sources' | 'quality'
export type MessageRow = {
  id: string
  role: 'assistant' | 'user' | 'system' | 'tool'
  text: string
  status?: 'accepted' | 'streaming' | 'completed' | 'interrupted' | 'failed' | 'archived'
}
