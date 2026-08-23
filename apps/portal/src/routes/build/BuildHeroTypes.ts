import type { ProjectCard } from '../../domains/platform/types'
import type { BuildComposerSkill } from '../../shared/ui/build-composer/BuildComposerTypes'

export interface BuildHeroProps {
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  loading: boolean
  selectedSkillIds: string[]
  selectedSkills: BuildComposerSkill[]
  onToggleSkill: (skillId: string) => void
  onGuessYou: () => void
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}
