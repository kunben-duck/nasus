import { BuildSkillIcon } from '../BuildSkillIcon'
import type { BuildComposerSkill } from './BuildComposerTypes'

export function SelectedSkillGrid({
  selectedSkills,
  onToggleSkill,
}: {
  selectedSkills: BuildComposerSkill[]
  onToggleSkill: (skillId: string) => void
}) {
  if (!selectedSkills.length) return null

  return (
    <div className="selected-skill-grid">
      {selectedSkills.map((skill) => (
        <button className="selected-skill-card" key={skill.id} onClick={() => onToggleSkill(skill.id)} type="button">
          <span className={`build-skill-icon tone-${skill.icon}`}>
            <BuildSkillIcon icon={skill.icon} />
          </span>
          <span>
            <strong>{skill.title}</strong>
            <small>{skill.copy}</small>
          </span>
          <i>×</i>
        </button>
      ))}
    </div>
  )
}
