const iconName: Record<string, string> = {
  git: 'account_tree',
  doc: 'description',
  test: 'fact_check',
  graph: 'hub',
  loop: 'sync',
  shield: 'verified_user',
}

export function BuildSkillIcon({ icon }: { icon: string }) {
  return <span className="material-symbols-outlined build-skill-symbol" aria-hidden="true">{iconName[icon] || 'extension'}</span>
}
