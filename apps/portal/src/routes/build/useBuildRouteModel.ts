import { useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import type { ProjectCard } from '../../domains/platform/types'
import { useConversation } from '../../domains/agent/useConversation'
import { buildSkillCards } from '../../domains/platform/build-skills'
import { useBuildProjects } from './useBuildProjects'
import { useBuildPromptRunner } from './useBuildPromptRunner'
import { useBuildSkillSelection } from './useBuildSkillSelection'

export function useBuildRouteModel() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const buildConversation = useConversation('build', 'build', 'Build')
  const buildProjects = useBuildProjects()
  const promptRunner = useBuildPromptRunner({
    buildConversation,
    navigate,
    queryClient,
  })
  const buildSkillSelection = useBuildSkillSelection({
    prompt: promptRunner.prompt,
    setPrompt: promptRunner.setPrompt,
  })

  function openProject(project: ProjectCard) {
    if (project.preview_only) {
      promptRunner.setPrompt(
        `Create a new quality project based on the ${project.name} starting point. Guide me through importing the Git repository, US documents, and test assets before initializing the system image.`,
      )
      return
    }
    navigate(`/projects/${encodeURIComponent(project.id)}`)
  }
  const selectedSkills = useMemo(
    () => buildSkillCards.filter((skill) => buildSkillSelection.selectedSkillIds.includes(skill.id)),
    [buildSkillSelection.selectedSkillIds],
  )

  return {
    projects: buildProjects.projects,
    prompt: promptRunner.prompt,
    setPrompt: promptRunner.setPrompt,
    selectedSkillIds: buildSkillSelection.selectedSkillIds,
    selectedSkills,
    openProject,
    runPrompt: promptRunner.runPrompt,
    toggleBuildSkill: buildSkillSelection.toggleBuildSkill,
    guessBuildPrompt: buildSkillSelection.guessBuildPrompt,
    loading: promptRunner.isPromptRunning || buildConversation.isSending || buildConversation.isLoading || !buildConversation.conversationId,
    statusDependencies: buildProjects.statusDependencies,
  }
}
