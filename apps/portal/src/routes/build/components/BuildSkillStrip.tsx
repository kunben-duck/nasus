import { buildSkillCards, type BuildSkillId } from '../../../domains/platform/build-skills'
import { BuildSkillIcon } from '../../../shared/ui/BuildSkillIcon'
import { useI18n } from '../../../shared/i18n/I18nProvider'
import type { MessageKey } from '../../../shared/i18n/messages'

export function BuildSkillStrip({
  activeSkill,
  onSelectSkill,
}: {
  activeSkill: BuildSkillId | null
  onSelectSkill: (skillId: BuildSkillId) => void
}) {
  const { t } = useI18n()
  return (
    <div className="source-chip-row" aria-label={t('Build skills')}>
      {buildSkillCards.map((skill) => (
        <button
          className={`build-skill-card ${activeSkill === skill.id ? 'active' : ''}`}
          key={skill.id}
          onClick={() => onSelectSkill(skill.id)}
          type="button"
          aria-expanded={activeSkill === skill.id}
          aria-controls={activeSkill === skill.id ? 'build-shortcut-panel' : undefined}
        >
          <span className={`build-skill-icon tone-${skill.icon}`}>
            <BuildSkillIcon icon={skill.icon} />
          </span>
          <span>
            <strong>{t(skill.title as MessageKey)}</strong>
            <small>{t(skill.copy as MessageKey)}</small>
          </span>
        </button>
      ))}
    </div>
  )
}
