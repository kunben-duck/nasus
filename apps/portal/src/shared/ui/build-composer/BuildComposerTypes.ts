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
  stopPrompt: () => void
  loading: boolean
  streaming: boolean
  selectedSkills: BuildComposerSkill[]
  onToggleSkill: (skillId: string) => void
  onGuessYou: () => void
}
