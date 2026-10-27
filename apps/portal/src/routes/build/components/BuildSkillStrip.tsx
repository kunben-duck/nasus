import { buildSkillCards } from '../../../domains/platform/build-skills'
import { BuildSkillIcon } from '../../../shared/ui/BuildSkillIcon'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../shared/i18n/messages'

export function BuildSkillStrip({
  selectedSkillIds,
  onToggleSkill,
}: {
  selectedSkillIds: string[]
  onToggleSkill: (skillId: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="source-chip-row" aria-label={t('Build skills')}>
      {buildSkillCards.map((skill) => (
        <button
          className={`build-skill-card ${selectedSkillIds.includes(skill.id) ? 'active' : ''}`}
          key={skill.id}
          onClick={() => onToggleSkill(skill.id)}
          type="button"
        >
          <span className={`build-skill-icon tone-${skill.icon}`}>
            <BuildSkillIcon icon={skill.icon} />
          </span>
          <span>
            <strong>{t(skill.title as MessageKey)}</strong>
            <small>{t(skill.copy as MessageKey)}</small>
          </span>
          {selectedSkillIds.includes(skill.id) ? <i>×</i> : null}
        </button>
      ))}
    </div>
  )
}
