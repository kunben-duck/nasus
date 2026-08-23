import { BuildComposerActions } from './build-composer/BuildComposerActions'
import { BuildPromptInput } from './build-composer/BuildPromptInput'
import type { BuildComposerProps } from './build-composer/BuildComposerTypes'
import { SelectedSkillGrid } from './build-composer/SelectedSkillGrid'

export function BuildComposer({
  prompt,
  setPrompt,
  runPrompt,
  loading,
  selectedSkills,
  onToggleSkill,
  onGuessYou,
}: BuildComposerProps) {
  const hasPrompt = prompt.trim().length > 0

  return (
    <div className="hero-composer">
      <div className="hero-composer-content">
        <SelectedSkillGrid selectedSkills={selectedSkills} onToggleSkill={onToggleSkill} />
        <BuildPromptInput prompt={prompt} setPrompt={setPrompt} runPrompt={runPrompt} />
        <BuildComposerActions hasPrompt={hasPrompt} loading={loading} onGuessYou={onGuessYou} runPrompt={runPrompt} />
      </div>
    </div>
  )
}
