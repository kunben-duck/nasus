import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useConversation } from '../../domains/agent/useConversation'
import { useBuildProjects } from './useBuildProjects'
import { useBuildPromptRunner } from './useBuildPromptRunner'
import { useBuildSkillSelection } from './useBuildSkillSelection'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function useBuildRouteModel() {
  const { t } = useI18n()
  const [search, setSearch] = useSearchParams()
  const session = search.get('session')
  const spaceId = session && /^[a-zA-Z0-9-]{1,64}$/.test(session) ? `build-${session}` : 'build'
  const queryClient = useQueryClient()
  const buildConversation = useConversation('build', spaceId, t('Build'))
  const buildProjects = useBuildProjects()
  const promptRunner = useBuildPromptRunner({ buildConversation, queryClient })
  const buildSkillSelection = useBuildSkillSelection({
    prompt: promptRunner.prompt,
    setPrompt: promptRunner.setPrompt,
  })

  return {
    conversation: buildConversation.conversation,
    sendPrompt: promptRunner.sendPrompt,
    newBuild: () => {
      promptRunner.setPrompt('')
      setSearch({ session: crypto.randomUUID() })
    },
    prompt: promptRunner.prompt,
    setPrompt: promptRunner.setPrompt,
    selectedSkills: buildSkillSelection.selectedSkills,
    runPrompt: promptRunner.runPrompt,
    stopPrompt: promptRunner.stopPrompt,
    toggleBuildSkill: buildSkillSelection.toggleBuildSkill,
    guessBuildPrompt: buildSkillSelection.guessBuildPrompt,
    feedback: promptRunner.feedback,
    loading: promptRunner.isPromptRunning || buildConversation.isSending || buildConversation.isLoading || !buildConversation.conversationId,
    streaming: promptRunner.isPromptRunning || Boolean(
      buildConversation.activeTurn
      && !['completed', 'delegated', 'interrupted', 'failed'].includes(buildConversation.activeTurn.status),
    ),
    statusDependencies: buildProjects.statusDependencies,
  }
}
