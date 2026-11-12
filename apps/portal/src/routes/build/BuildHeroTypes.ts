import type { ConversationSession } from '../../domains/agent/types'
import type { BuildComposerSkill } from '../../shared/ui/build-composer/BuildComposerTypes'

export interface BuildHeroProps {
  conversation?: ConversationSession
  sendPrompt: (content: string) => Promise<void>
  newBuild: () => void
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  stopPrompt: () => void
  loading: boolean
  streaming: boolean
  selectedSkills: BuildComposerSkill[]
  onToggleSkill: (skillId: string) => void
  onGuessYou: () => void
  feedback: { tone: 'assistant' | 'error'; text: string } | null
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}
