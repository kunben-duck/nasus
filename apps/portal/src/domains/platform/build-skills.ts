export type BuildSkillIconName = 'git' | 'doc' | 'test' | 'graph' | 'loop' | 'shield'

export type BuildSkillCard = {
  id: string
  title: string
  copy: string
  icon: BuildSkillIconName
  promptHint: string
  promptHintZh: string
}

export const buildSkillCards: BuildSkillCard[] = [
  {
    id: 'git',
    title: 'Import Git repository',
    copy: 'Read code modules and changed areas',
    icon: 'git',
    promptHint: 'import the Git repository',
    promptHintZh: '导入 Git 仓库',
  },
  {
    id: 'us',
    title: 'Import US documents',
    copy: 'Extract features and acceptance criteria',
    icon: 'doc',
    promptHint: 'import historical and current US documents',
    promptHintZh: '导入历史与当前 US 文档',
  },
  {
    id: 'tests',
    title: 'Import test assets',
    copy: 'Reuse cases and automation scripts',
    icon: 'test',
    promptHint: 'import historical test cases and automation scripts',
    promptHintZh: '导入历史测试用例和自动化脚本',
  },
  {
    id: 'baseline',
    title: 'Initialize system image',
    copy: 'Build the first official baseline',
    icon: 'graph',
    promptHint: 'initialize the system image baseline',
    promptHintZh: '初始化系统画像基线',
  },
  {
    id: 'quality',
    title: 'Start quality loop',
    copy: 'Generate scenarios and release evidence',
    icon: 'loop',
    promptHint: 'start the quality loop for the first version',
    promptHintZh: '为首个版本启动质量闭环',
  },
  {
    id: 'release',
    title: 'Assess release quality',
    copy: 'Score readiness and blockers',
    icon: 'shield',
    promptHint: 'assess release quality and open blockers',
    promptHintZh: '评估发布质量与未解决阻塞项',
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

export function composeBuildPrompt(skillIds: string[], language: 'en' | 'zh' = 'en') {
  const selected = buildSkillCards.filter((skill) => skillIds.includes(skill.id))
  if (!selected.length) {
    return language === 'zh'
      ? '创建一个新的质量项目，并在执行任何高风险动作前引导我补充必要配置。'
      : 'Create a new quality project and guide me through the missing setup before any high-risk action.'
  }
  if (language === 'zh') {
    const actions = selected.map((skill) => skill.promptHintZh).join('、')
    return `创建一个新的质量项目。请${actions}，并在执行任何高风险动作前询问缺失配置。`
  }
  const actions = selected.map((skill) => skill.promptHint).join(' and ')
  return `Create a new quality project. Please ${actions}, then ask for the missing setup before any high-risk action.`
}
