import type { ProjectCard } from '../../domains/platform/types'
import type { BuildComposerSkill } from '../../shared/ui/build-composer/BuildComposerTypes'

export interface BuildHeroProps {
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  stopPrompt: () => void
  loading: boolean
  streaming: boolean
  selectedSkillIds: string[]
  selectedSkills: BuildComposerSkill[]
  onToggleSkill: (skillId: string) => void
  onGuessYou: () => void
  feedback: { tone: 'assistant' | 'error'; text: string } | null
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}
