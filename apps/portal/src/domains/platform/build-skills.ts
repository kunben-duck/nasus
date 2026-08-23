export type BuildSkillIconName = 'git' | 'doc' | 'test' | 'graph' | 'loop' | 'shield'

export type BuildSkillCard = {
  id: string
  title: string
  copy: string
  icon: BuildSkillIconName
  promptHint: string
}

export const buildSkillCards: BuildSkillCard[] = [
  {
    id: 'git',
    title: 'Import Git repository',
    copy: 'Read code modules and changed areas',
    icon: 'git',
    promptHint: 'import the Git repository',
  },
  {
    id: 'us',
    title: 'Import US documents',
    copy: 'Extract features and acceptance criteria',
    icon: 'doc',
    promptHint: 'import historical and current US documents',
  },
  {
    id: 'tests',
    title: 'Import test assets',
    copy: 'Reuse cases and automation scripts',
    icon: 'test',
    promptHint: 'import historical test cases and automation scripts',
  },
  {
    id: 'baseline',
    title: 'Initialize system image',
    copy: 'Build the first official baseline',
    icon: 'graph',
    promptHint: 'initialize the system image baseline',
  },
  {
    id: 'quality',
    title: 'Start quality loop',
    copy: 'Generate scenarios and release evidence',
    icon: 'loop',
    promptHint: 'start the quality loop for the first version',
  },
  {
    id: 'release',
    title: 'Assess release quality',
    copy: 'Score readiness and blockers',
    icon: 'shield',
    promptHint: 'assess release quality and open blockers',
  },
]

export function normalizeProjectName(prompt: string) {
  const quoted = prompt.match(/["“”']([^"“”']+)["“”']/)
  if (quoted?.[1]) return quoted[1].trim()

  const chinese = prompt.match(/(?:叫|名为|名字叫)\s*([^，。,\n]+)/)
  if (chinese?.[1]) return chinese[1].trim()

  const english = prompt.match(/(?:project|项目)(?: called| named| name is)?\s+([A-Za-z0-9][A-Za-z0-9 _-]{1,50})/i)
  if (english?.[1]) return english[1].trim()

  return 'New Quality Project'
}

export function composeBuildPrompt(skillIds: string[]) {
  const selected = buildSkillCards.filter((skill) => skillIds.includes(skill.id))
  if (!selected.length) {
    return 'Create a new quality project and guide me through the missing setup before any high-risk action.'
  }
  const actions = selected.map((skill) => skill.promptHint).join(' and ')
  return `Create a new quality project. Please ${actions}, then ask for the missing setup before any high-risk action.`
}
