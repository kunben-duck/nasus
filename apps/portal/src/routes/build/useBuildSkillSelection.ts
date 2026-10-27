import { useMemo, useState } from 'react'

import { buildSkillCards, composeBuildPrompt } from '../../domains/platform/build-skills'
import { useI18n } from '../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../shared/i18n/messages'

export function useBuildSkillSelection({
  prompt,
  setPrompt,
}: {
  prompt: string
  setPrompt: (value: string) => void
}) {
  const { locale, t } = useI18n()
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([])
  const selectedSkills = useMemo(() => buildSkillCards.filter(
    (skill) => selectedSkillIds.includes(skill.id),
  ).map((skill) => ({
    ...skill,
    title: t(skill.title as MessageKey),
    copy: t(skill.copy as MessageKey),
  })), [selectedSkillIds, t])

  function toggleBuildSkill(skillId: string) {
    setSelectedSkillIds((current) => {
      const next = current.includes(skillId)
        ? current.filter((item) => item !== skillId)
        : [...current, skillId]
      if (prompt.trim()) {
        setPrompt(composeBuildPrompt(next, locale))
      }
      return next
    })
  }

  function guessBuildPrompt() {
    const recommended = ['git', 'us']
    setSelectedSkillIds(recommended)
    setPrompt(composeBuildPrompt(recommended, locale))
  }

  return {
    selectedSkillIds,
    selectedSkills,
    toggleBuildSkill,
    guessBuildPrompt,
  }
}
