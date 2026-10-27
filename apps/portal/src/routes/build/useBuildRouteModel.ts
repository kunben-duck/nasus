import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import type { ProjectCard } from '../../domains/platform/types'
import { useConversation } from '../../domains/agent/useConversation'
import { useBuildProjects } from './useBuildProjects'
import { useBuildPromptRunner } from './useBuildPromptRunner'
import { useBuildSkillSelection } from './useBuildSkillSelection'
import { useI18n } from '../../shared/i18n/I18nProvider'

export function useBuildRouteModel() {
  const navigate = useNavigate()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const buildConversation = useConversation('build', 'build', t('Build'))
  const buildProjects = useBuildProjects()
  const promptRunner = useBuildPromptRunner({ buildConversation, navigate, queryClient })
  const buildSkillSelection = useBuildSkillSelection({
    prompt: promptRunner.prompt,
    setPrompt: promptRunner.setPrompt,
  })

  function openProject(project: ProjectCard) {
    if (project.preview_only) {
      promptRunner.setPrompt(t(
        'Create a new quality project based on the {name} starting point. Guide me through importing the Git repository, US documents, and test assets before initializing the system image.',
        { name: project.name },
      ))
      return
    }
    navigate(`/projects/${encodeURIComponent(project.id)}`)
  }
  return {
    projects: buildProjects.projects,
    prompt: promptRunner.prompt,
    setPrompt: promptRunner.setPrompt,
    selectedSkillIds: buildSkillSelection.selectedSkillIds,
    selectedSkills: buildSkillSelection.selectedSkills,
    openProject,
    runPrompt: promptRunner.runPrompt,
    stopPrompt: promptRunner.stopPrompt,
    toggleBuildSkill: buildSkillSelection.toggleBuildSkill,
    guessBuildPrompt: buildSkillSelection.guessBuildPrompt,
    feedback: promptRunner.feedback,
    loading: promptRunner.isPromptRunning || buildConversation.isSending || buildConversation.isLoading || !buildConversation.conversationId,
    streaming: promptRunner.isPromptRunning || Boolean(
      buildConversation.activeTurn
      && !['completed', 'interrupted', 'failed'].includes(buildConversation.activeTurn.status),
    ),
    statusDependencies: buildProjects.statusDependencies,
  }
}
