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
    const next = selectedSkillIds.includes(skillId)
      ? selectedSkillIds.filter((item) => item !== skillId)
      : [...selectedSkillIds, skillId]
    if (prompt === composeBuildPrompt(selectedSkillIds, locale)) setPrompt(composeBuildPrompt(next, locale))
    setSelectedSkillIds(next)
  }

  function guessBuildPrompt() {
    if (prompt.trim()) return
    const recommended = ['git', 'us']
    setSelectedSkillIds(recommended)
    setPrompt(composeBuildPrompt(recommended, locale))
  }

  return {
    selectedSkills,
    toggleBuildSkill,
    guessBuildPrompt,
  }
}
