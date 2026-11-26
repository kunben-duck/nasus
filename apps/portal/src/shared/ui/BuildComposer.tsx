import { BuildComposerActions } from './build-composer/BuildComposerActions'
import { ChatPromptInput } from './chat-composer/ChatPromptInput'
import { useI18n } from '../i18n/I18nProvider'
import type { BuildComposerProps } from './build-composer/BuildComposerTypes'
import { SelectedSkillGrid } from './build-composer/SelectedSkillGrid'

export function BuildComposer({
  prompt, promptHistory, setPrompt, runPrompt, stopPrompt,
  loading, streaming, selectedSkills, onToggleSkill, onGuessYou,
}: BuildComposerProps) {
  const hasPrompt = prompt.trim().length > 0
  const { t } = useI18n()
  return (
    <div className="hero-composer">
      <div className="hero-composer-content">
        <SelectedSkillGrid selectedSkills={selectedSkills} onToggleSkill={onToggleSkill} />
        <ChatPromptInput testId="build-agent-input" placeholder={t('Describe a quality project and let Nasus do the rest')}
          prompt={prompt} promptHistory={promptHistory} setPrompt={setPrompt}
          runPrompt={runPrompt} busy={loading || streaming}
        />
        <BuildComposerActions
          hasPrompt={hasPrompt}
          loading={loading}
          streaming={streaming}
          onGuessYou={onGuessYou}
          runPrompt={runPrompt}
          stopPrompt={stopPrompt}
        />
      </div>
    </div>
  )
}
