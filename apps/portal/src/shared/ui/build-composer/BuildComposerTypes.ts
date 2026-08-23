export type BuildComposerSkill = {
  id: string
  title: string
  copy: string
  icon: string
}

export interface BuildComposerProps {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  loading: boolean
  selectedSkills: BuildComposerSkill[]
  onToggleSkill: (skillId: string) => void
  onGuessYou: () => void
}
