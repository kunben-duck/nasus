import { useState } from 'react'

import { composeBuildPrompt } from '../../domains/platform/build-skills'

export function useBuildSkillSelection({
  prompt,
  setPrompt,
}: {
  prompt: string
  setPrompt: (value: string) => void
}) {
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([])

  function toggleBuildSkill(skillId: string) {
    setSelectedSkillIds((current) => {
      const next = current.includes(skillId)
        ? current.filter((item) => item !== skillId)
        : [...current, skillId]
      if (prompt.trim()) {
        setPrompt(composeBuildPrompt(next))
      }
      return next
    })
  }

  function guessBuildPrompt() {
    const recommended = ['git', 'us']
    setSelectedSkillIds(recommended)
    setPrompt(composeBuildPrompt(recommended))
  }

  return {
    selectedSkillIds,
    toggleBuildSkill,
    guessBuildPrompt,
  }
}
