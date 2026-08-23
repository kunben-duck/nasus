import { buildSkillCards } from '../../../domains/platform/build-skills'
import { BuildSkillIcon } from '../../../shared/ui/BuildSkillIcon'

export function BuildSkillStrip({
  selectedSkillIds,
  onToggleSkill,
}: {
  selectedSkillIds: string[]
  onToggleSkill: (skillId: string) => void
}) {
  return (
    <div className="source-chip-row" aria-label="Build skills">
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
            <strong>{skill.title}</strong>
            <small>{skill.copy}</small>
          </span>
          {selectedSkillIds.includes(skill.id) ? <i>×</i> : null}
        </button>
      ))}
    </div>
  )
}
