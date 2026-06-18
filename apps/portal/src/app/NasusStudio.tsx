import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../features/api'
import type {
  AgentGoal,
  ConversationSession,
  CustomModelConfig,
  ModelRoute,
  ProjectCard,
  SettingsConnectionResult,
  StudioSettings,
  StudioSettingsConnectionTestRequest,
  SystemImageData,
} from '../features/types'
import { useConversation } from '../hooks/useConversation'

type StudioView = 'build' | 'dashboard' | 'documentation' | 'project'
type AgentMode = 'planning' | 'sources' | 'quality'
type MessageRow = { role: 'assistant' | 'user' | 'system' | 'tool'; text: string }
type SidebarIconName = 'notifications' | 'settings' | 'search' | 'key'
type BuildSkillCard = {
  id: string
  title: string
  copy: string
  icon: 'git' | 'doc' | 'test' | 'graph' | 'loop' | 'shield'
  promptHint: string
}

const starterProjects: ProjectCard[] = [
  {
    id: 'local_payment',
    name: 'Payment System',
    code: 'PAY',
    summary: 'Checkout, saved cards, refunds, and release quality closure.',
    status: 'active',
    risk: 'medium',
    progress: 68,
    active_version: '2026.Q2',
    blocked_items: 2,
    pending_approvals: 1,
    system_image_status: 'ready',
  },
  {
    id: 'local_growth',
    name: 'Growth Console',
    code: 'GRO',
    summary: 'Campaign configuration, user targeting, and approval handoff.',
    status: 'draft',
    risk: 'low',
    progress: 24,
    active_version: 'Discovery',
    blocked_items: 0,
    pending_approvals: 0,
    system_image_status: 'draft',
  },
]

const buildSkillCards: BuildSkillCard[] = [
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

function SidebarIcon({ name }: { name: SidebarIconName }) {
  return <span className="material-symbols-outlined" aria-hidden="true">{name}</span>
}

function BuildSkillIcon({ icon }: { icon: BuildSkillCard['icon'] }) {
  const iconName: Record<BuildSkillCard['icon'], string> = {
    git: 'account_tree',
    doc: 'description',
    test: 'fact_check',
    graph: 'hub',
    loop: 'sync',
    shield: 'verified_user',
  }

  return <span className="material-symbols-outlined build-skill-symbol" aria-hidden="true">{iconName[icon]}</span>
}

const agentCards = [
  {
    title: 'System Image Builder',
    icon: '✦',
    tone: 'gold',
    copy: 'Builds and updates the project baseline from code, historical US docs, and test assets.',
  },
  {
    title: 'Quality Loop Agent',
    icon: '⌁',
    tone: 'green',
    copy: 'Plans scenarios, cases, execution, failure analysis, and release readiness from one goal.',
  },
  {
    title: 'Release Assessor',
    icon: '◇',
    tone: 'blue',
    copy: 'Scores go-live quality using evidence, open risks, run results, and governance state.',
  },
  {
    title: 'Repo Maintainer',
    icon: '⌘',
    tone: 'purple',
    copy: 'Reads code impact, maps changed modules to US scope, and proposes test coverage deltas.',
  },
]

function normalizeProjectName(prompt: string) {
  const quoted = prompt.match(/["“”']([^"“”']+)["“”']/)
  if (quoted?.[1]) return quoted[1].trim()

  const chinese = prompt.match(/(?:叫|名为|名字叫)\s*([^，。,\n]+)/)
  if (chinese?.[1]) return chinese[1].trim()

  const english = prompt.match(/(?:project|项目)(?: called| named| name is)?\s+([A-Za-z0-9][A-Za-z0-9 _-]{1,50})/i)
  if (english?.[1]) return english[1].trim()

  return 'New Quality Project'
}

function composeBuildPrompt(skillIds: string[]) {
  const selected = buildSkillCards.filter((skill) => skillIds.includes(skill.id))
  if (!selected.length) {
    return 'Create a new quality project and guide me through the missing setup before any high-risk action.'
  }
  const actions = selected.map((skill) => skill.promptHint).join(' and ')
  return `Create a new quality project. Please ${actions}, then ask for the missing setup before any high-risk action.`
}

function useTheme(settings?: StudioSettings) {
  useEffect(() => {
    const root = document.documentElement
    const theme = settings?.theme ?? 'dark'
    const media = window.matchMedia('(prefers-color-scheme: light)')

    function applyTheme() {
      root.dataset.theme = theme === 'system'
        ? (media.matches ? 'light' : 'dark')
        : theme
    }

    applyTheme()
    if (theme !== 'system') return

    media.addEventListener('change', applyTheme)
    return () => media.removeEventListener('change', applyTheme)
  }, [settings?.theme])
}

export function NasusStudio() {
  const queryClient = useQueryClient()
  const [view, setView] = useState<StudioView>('build')
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [agentMode, setAgentMode] = useState<AgentMode>('planning')
  const [fallbackMessages, setFallbackMessages] = useState<MessageRow[]>([
    {
      role: 'assistant',
      text: 'Tell me what you want to ship. I can create the project, connect sources, build the system image, and start the quality loop.',
    },
  ])
  const [selectedBuildSkillIds, setSelectedBuildSkillIds] = useState<string[]>([])
  const [isPromptRunning, setIsPromptRunning] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: api.getSettings })
  const dashboardQuery = useQuery({ queryKey: ['dashboard'], queryFn: api.getDashboard })
  const buildQuery = useQuery({ queryKey: ['build'], queryFn: api.getBuild })
  const buildConversation = useConversation('build', 'build', 'Build')
  useTheme(settingsQuery.data)

  useEffect(() => {
    if (!settingsOpen) return

    function closeSettingsOnOutsidePointer(event: PointerEvent) {
      const target = event.target as Element | null
      if (!target) return
      if (target.closest('.settings-pop') || target.closest('[data-settings-toggle]')) return
      setSettingsOpen(false)
    }

    document.addEventListener('pointerdown', closeSettingsOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', closeSettingsOnOutsidePointer)
  }, [settingsOpen])

  const projects = useMemo(() => {
    const remote = dashboardQuery.data?.projects ?? buildQuery.data?.drafts ?? []
    return remote.length ? remote : starterProjects
  }, [buildQuery.data?.drafts, dashboardQuery.data?.projects])

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? projects[0]
  const projectConversation = useConversation('project', activeProject?.id ?? 'project', activeProject?.name ?? 'Project')
  const systemImageQuery = useQuery({
    queryKey: ['system-image', activeProject?.id],
    queryFn: () => api.getSystemImage(activeProject!.id),
    enabled: Boolean(activeProject?.id),
  })

  const visibleMessages = useMemo(() => {
    const conversation = view === 'project' ? projectConversation.conversation : buildConversation.conversation
    const rows = toMessageRows(conversation)
    return rows.length ? rows : fallbackMessages
  }, [buildConversation.conversation, fallbackMessages, projectConversation.conversation, view])
  const pendingProjectGoal = useMemo(
    () => projectConversation.conversation?.agent_goals.find((goal) => goal.status === 'paused' && goal.pause_reason === 'waiting_confirmation'),
    [projectConversation.conversation],
  )

  const updateSettings = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.updateSettings(payload),
    onSuccess: (settings) => {
      queryClient.setQueryData(['settings'], settings)
    },
  })
  const testSettingsConnection = useMutation({
    mutationFn: (payload: StudioSettingsConnectionTestRequest) => api.testSettingsConnection(payload),
  })

  const initializeSystemImage = useMutation({
    mutationFn: async () => {
      if (!activeProject) return null
      const conversation = await api.ensureConversation('project', activeProject.id, activeProject.name)
      return api.invokeTool({
        conversation_id: conversation.id,
        tool_id: 'system_image.baseline.initialize',
        input: { project_id: activeProject.id },
        initiator_surface: 'ui',
        initiator_actor: 'user',
      })
    },
    onSuccess: async () => {
      if (!activeProject) return
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      await queryClient.invalidateQueries({ queryKey: ['build'] })
      await queryClient.invalidateQueries({ queryKey: ['project', activeProject.id] })
      await queryClient.invalidateQueries({ queryKey: ['system-image', activeProject.id] })
      await queryClient.invalidateQueries({ queryKey: ['conversation', projectConversation.conversationId] })
    },
  })

  async function runPrompt() {
    const text = prompt.trim()
    if (!text) return

    setPrompt('')
    setFallbackMessages((messages) => [...messages, { role: 'user', text }])
    setIsPromptRunning(true)

    try {
      if (view === 'project') {
        await projectConversation.sendMessage(text)
        if (activeProject) {
          await queryClient.invalidateQueries({ queryKey: ['system-image', activeProject.id] })
          await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
        }
        return
      }

      await buildConversation.sendMessage(text)
      await queryClient.invalidateQueries({ queryKey: ['build'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })

      const dashboard = await queryClient.fetchQuery({ queryKey: ['dashboard'], queryFn: api.getDashboard })
      const requestedName = normalizeProjectName(text).toLowerCase()
      const created = dashboard.projects.find((project) => project.name.toLowerCase() === requestedName)
      if (created) {
        setActiveProjectId(created.id)
        setView('project')
      }
    } catch {
      setFallbackMessages((messages) => [
        ...messages,
        {
          role: 'assistant',
          text: 'The API is not reachable, so this screen is staying in visual preview mode. Once the backend is running, this prompt will go through Conversation → Tool Invocation → Domain Object.',
        },
      ])
    } finally {
      setIsPromptRunning(false)
    }
  }

  function toggleBuildSkill(skillId: string) {
    setSelectedBuildSkillIds((current) => {
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
    setSelectedBuildSkillIds(recommended)
    setPrompt(composeBuildPrompt(recommended))
  }

  function openProject(project: ProjectCard) {
    setActiveProjectId(project.id)
    setView('project')
    setFallbackMessages((messages) => [
      ...messages,
      {
        role: 'assistant',
        text: `Opened ${project.name}. I can inspect system image freshness, quality loop progress, runs, and release readiness here.`,
      },
    ])
  }

  function toggleSidebar() {
    setSettingsOpen(false)
    setSidebarCollapsed((value) => !value)
  }

  async function askProject(promptText: string) {
    setPrompt(promptText)
    if (view !== 'project') return
    setIsPromptRunning(true)
    try {
      await projectConversation.sendMessage(promptText)
      if (activeProject) {
        await queryClient.invalidateQueries({ queryKey: ['system-image', activeProject.id] })
        await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      }
    } finally {
      setPrompt('')
      setIsPromptRunning(false)
    }
  }

  async function confirmPendingGoal() {
    if (!pendingProjectGoal) return
    setIsPromptRunning(true)
    try {
      await projectConversation.sendMessage('确认，继续执行')
      if (activeProject) {
        await queryClient.invalidateQueries({ queryKey: ['system-image', activeProject.id] })
        await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      }
    } finally {
      setIsPromptRunning(false)
    }
  }

  const isProjectSpace = view === 'project'

  return (
    <div className={`nasus-app ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="studio-sidebar">
        <div className="brand-row">
          <img className="brand-mark" src="/nasus.png" alt="Nasus" />
          <div>
            <div className="brand-name">Nasus Studio</div>
          </div>
          {isProjectSpace ? (
            <button className="round-icon subtle" onClick={() => setView('dashboard')} aria-label="Back to dashboard">
              ←
            </button>
          ) : null}
        </div>

        {isProjectSpace ? (
          <ProjectNav project={activeProject} setView={setView} />
        ) : (
          <GlobalNav view={view} setView={setView} />
        )}

        <div className="sidebar-spacer" />
        <div className="upgrade-card">
          <strong>Agent autonomy</strong>
          <span>All product actions are tools. Chat and buttons share the same command surface.</span>
        </div>
        <div className="sidebar-actions">
          <button className="icon-tile" aria-label="Notifications"><SidebarIcon name="notifications" /></button>
          <button className="icon-tile" aria-label="Settings" data-settings-toggle onClick={() => setSettingsOpen((value) => !value)}>
            <SidebarIcon name="settings" />
          </button>
          <button className="icon-tile" aria-label="Search"><SidebarIcon name="search" /></button>
          <button className="icon-tile" aria-label="API key"><SidebarIcon name="key" /></button>
        </div>
        <div className="account-pill">
          <span className="avatar">u</span>
          <span>uben@example.com</span>
        </div>
      </aside>

      <main className={`studio-main ${isProjectSpace ? 'with-right-panel' : ''}`}>
        <div className="terms-bar">
          <span>Nasus first production baseline · system image + agent + quality loop</span>
          <button>Learn more</button>
          <button>Dismiss</button>
        </div>

        {!isProjectSpace ? (
          <TopLevelContent
            view={view}
            projects={projects}
            openProject={openProject}
            prompt={prompt}
            setPrompt={setPrompt}
            runPrompt={runPrompt}
            loading={isPromptRunning || buildConversation.isSending}
            selectedSkillIds={selectedBuildSkillIds}
            onToggleSkill={toggleBuildSkill}
            onGuessYou={guessBuildPrompt}
            sidebarCollapsed={sidebarCollapsed}
            toggleSidebar={toggleSidebar}
          />
        ) : null}
        {isProjectSpace && activeProject ? (
          <ProjectWorkspace
            project={activeProject}
            systemImage={systemImageQuery.data}
            mode={agentMode}
            setMode={setAgentMode}
            messages={visibleMessages}
            pendingGoal={pendingProjectGoal}
            prompt={prompt}
            setPrompt={setPrompt}
            runPrompt={runPrompt}
            askProject={askProject}
            confirmPendingGoal={confirmPendingGoal}
            initializeSystemImage={() => initializeSystemImage.mutate()}
            loading={isPromptRunning || projectConversation.isSending || initializeSystemImage.isPending}
            sidebarCollapsed={sidebarCollapsed}
            toggleSidebar={toggleSidebar}
          />
        ) : null}
      </main>

      {isProjectSpace ? <RunSettingsPanel project={activeProject} systemImage={systemImageQuery.data} /> : null}
      {settingsOpen ? (
        <SettingsPopover
          settings={settingsQuery.data}
          testing={testSettingsConnection.isPending}
          testResult={testSettingsConnection.data}
          onTheme={(theme) => updateSettings.mutate({ theme })}
          onLanguage={(language) => updateSettings.mutate({ language })}
          onNotification={(notification_mode) => updateSettings.mutate({ notification_mode })}
          onSaveModel={(payload) => updateSettings.mutate(payload)}
          onTestModel={(payload) => testSettingsConnection.mutate(payload)}
        />
      ) : null}
    </div>
  )
}

function toMessageRows(conversation?: ConversationSession): MessageRow[] {
  if (!conversation) return []
  return conversation.messages
    .filter((message) => message.role !== 'system')
    .map((message) => ({
      role: message.role,
      text: message.blocks.map((block) => block.text).filter(Boolean).join('\n'),
    }))
    .filter((message) => message.text.trim().length > 0)
}

function GlobalNav({ view, setView }: { view: StudioView; setView: (view: StudioView) => void }) {
  return (
    <nav className="nav-stack">
      <SectionLabel label="Explore" />
      <NavButton active={view === 'build'} label="Build" icon="+" onClick={() => setView('build')} />
      <NavButton active={view === 'dashboard'} label="Dashboard" icon="◔" onClick={() => setView('dashboard')} />
      <SectionLabel label="Quality" />
      <NavButton active={false} label="System image" icon="▦" onClick={() => setView('dashboard')} />
      <NavButton active={false} label="Quality loops" icon="⌁" onClick={() => setView('dashboard')} />
      <NavButton active={false} label="Runs" icon="▻" onClick={() => setView('dashboard')} />
      <SectionLabel label="Manage" />
      <NavButton active={view === 'documentation'} label="Documentation" icon="□" onClick={() => setView('documentation')} />
    </nav>
  )
}

function ProjectNav({ project, setView }: { project?: ProjectCard; setView: (view: StudioView) => void }) {
  return (
    <nav className="nav-stack">
      <SectionLabel label={project?.code ?? 'Project'} />
      <div className="project-mini">
        <strong>{project?.name ?? 'Project Space'}</strong>
        <span>{project?.active_version ?? 'No version'} · {project?.progress ?? 0}% closed</span>
      </div>
      <NavButton active label="Agent workspace" icon="✦" onClick={() => setView('project')} />
      <NavButton active={false} label="System image" icon="▦" onClick={() => setView('project')} />
      <NavButton active={false} label="Quality loop" icon="⌁" onClick={() => setView('project')} />
      <NavButton active={false} label="Runs" icon="▻" onClick={() => setView('project')} />
      <NavButton active={false} label="Governance" icon="◇" onClick={() => setView('project')} />
    </nav>
  )
}

function SectionLabel({ label }: { label: string }) {
  return <div className="section-label">{label}</div>
}

function NavButton({ active, label, icon, onClick }: { active: boolean; label: string; icon: string; onClick: () => void }) {
  return (
    <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick}>
      <span>{icon}</span>
      <span>{label}</span>
      {label === 'Dashboard' ? <span className="nav-chevron">›</span> : null}
    </button>
  )
}

function TopLevelContent({
  view,
  projects,
  openProject,
  prompt,
  setPrompt,
  runPrompt,
  loading,
  selectedSkillIds,
  onToggleSkill,
  onGuessYou,
  sidebarCollapsed,
  toggleSidebar,
}: {
  view: StudioView
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  loading: boolean
  selectedSkillIds: string[]
  onToggleSkill: (skillId: string) => void
  onGuessYou: () => void
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}) {
  if (view === 'dashboard') {
    return (
      <section className="top-level-grid">
        <div className="page-heading compact">
          <span className="eyebrow">Dashboard</span>
          <h1>Global quality cockpit</h1>
          <p>Ask about progress, risk, system image freshness, or release readiness across all projects.</p>
        </div>
        <div className="metric-grid">
          <MetricCard label="Active projects" value={projects.length.toString()} />
          <MetricCard label="Blocked items" value={projects.reduce((sum, item) => sum + item.blocked_items, 0).toString()} />
          <MetricCard label="Approvals" value={projects.reduce((sum, item) => sum + item.pending_approvals, 0).toString()} />
        </div>
        <ProjectGallery projects={projects} openProject={openProject} />
      </section>
    )
  }

  if (view === 'documentation') {
    return (
      <section className="docs-page">
        <div className="page-heading compact">
          <span className="eyebrow">Documentation</span>
          <h1>How Nasus works</h1>
          <p>Product docs should explain the three product modules, not frontend/backend implementation details.</p>
        </div>
        <div className="doc-grid">
          <DocCard title="System Image" copy="The continuously updated project baseline built from code, US documents, and test assets." />
          <DocCard title="Agent Service" copy="The planner, memory, tool router, and swarm runtime that makes every action conversational." />
          <DocCard title="Quality Loop" copy="The evidence-driven flow from impact analysis to release assessment and baseline write-back." />
        </div>
      </section>
    )
  }

  return (
    <section className="build-hero">
      <button
        className="collapse-button"
        aria-expanded={!sidebarCollapsed}
        aria-label={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'}
        onClick={toggleSidebar}
        type="button"
      >
        <span className="material-symbols-outlined" aria-hidden="true">{sidebarCollapsed ? 'menu' : 'menu_open'}</span>
      </button>
      <div className="hero-title">
        <h1>Build quality projects with Nasus</h1>
      </div>
      <BuildComposer
        prompt={prompt}
        setPrompt={setPrompt}
        runPrompt={runPrompt}
        loading={loading}
        selectedSkillIds={selectedSkillIds}
        onToggleSkill={onToggleSkill}
        onGuessYou={onGuessYou}
      />
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
      <div className="gallery-panel">
        <div className="gallery-header">
          <h2>Discover project starting points</h2>
          <button>Browse templates →</button>
        </div>
        <ProjectGallery projects={projects} openProject={openProject} />
      </div>
    </section>
  )
}

function BuildComposer({
  prompt,
  setPrompt,
  runPrompt,
  loading,
  selectedSkillIds,
  onToggleSkill,
  onGuessYou,
}: {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  loading: boolean
  selectedSkillIds: string[]
  onToggleSkill: (skillId: string) => void
  onGuessYou: () => void
}) {
  const selectedSkills = buildSkillCards.filter((skill) => selectedSkillIds.includes(skill.id))
  const hasPrompt = prompt.trim().length > 0

  return (
    <div className="hero-composer">
      <div className="hero-composer-content">
        {selectedSkills.length ? (
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
        ) : null}
        <textarea
          data-testid="build-agent-input"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Describe a quality project and let Nasus do the rest"
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              runPrompt()
            }
          }}
        />
        <div className="composer-actions">
          <div className="composer-left">
            <button className="round-icon" aria-label="Speech to text" type="button">
              <span className="material-symbols-outlined composer-symbol" aria-hidden="true">mic</span>
            </button>
            <button className="round-icon" aria-label="Insert files" type="button">
              <span className="material-symbols-outlined composer-symbol" aria-hidden="true">add_circle</span>
            </button>
          </div>
          <div className="composer-right">
            <button className="composer-action-button guess-button" data-testid="build-agent-guess" onClick={onGuessYou} type="button">
              <span className="material-symbols-outlined action-spark" aria-hidden="true">auto_awesome</span>
              <span>I guess you</span>
            </button>
            {hasPrompt ? (
              <button className="composer-action-button build-submit-button" data-testid="build-agent-submit" onClick={runPrompt} disabled={loading}>
                <span>{loading ? 'Building...' : 'Build'}</span>
                {!loading ? <span className="action-shortcut">⌘↵</span> : null}
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}

function ProjectWorkspace({
  project,
  systemImage,
  mode,
  setMode,
  messages,
  pendingGoal,
  prompt,
  setPrompt,
  runPrompt,
  askProject,
  confirmPendingGoal,
  initializeSystemImage,
  loading,
  sidebarCollapsed,
  toggleSidebar,
}: {
  project: ProjectCard
  systemImage?: SystemImageData
  mode: AgentMode
  setMode: (mode: AgentMode) => void
  messages: MessageRow[]
  pendingGoal?: AgentGoal
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  askProject: (promptText: string) => void
  confirmPendingGoal: () => void
  initializeSystemImage: () => void
  loading: boolean
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}) {
  const cardActions: Record<string, () => void> = {
    'System Image Builder': initializeSystemImage,
    'Quality Loop Agent': () => askProject('Summarize the current quality loop status and recommend the next best action.'),
    'Release Assessor': () => askProject('Assess release readiness based on current evidence, open risks, and governance status.'),
    'Repo Maintainer': () => askProject('Inspect system image code quality and changed module risk for this project.'),
  }

  return (
    <section className="agent-workspace" data-testid="agent-workspace">
      <div className="workspace-toolbar">
        <button
          className="collapse-button"
          aria-expanded={!sidebarCollapsed}
          aria-label={sidebarCollapsed ? 'Expand navigation' : 'Collapse navigation'}
          onClick={toggleSidebar}
          type="button"
        >
          <span className="material-symbols-outlined" aria-hidden="true">{sidebarCollapsed ? 'menu' : 'menu_open'}</span>
        </button>
        <strong>{project.name}</strong>
        <div className="toolbar-actions">
          <button>Share</button>
          <button>＋</button>
          <button>⋮</button>
        </div>
      </div>
      <div className="agent-heading">
        <h1>Build with Agents</h1>
        <div className="segmented">
          <button className={mode === 'planning' ? 'active' : ''} onClick={() => setMode('planning')}>Agents</button>
          <button className={mode === 'sources' ? 'active' : ''} onClick={() => setMode('sources')}>Sources</button>
          <button className={mode === 'quality' ? 'active' : ''} onClick={() => setMode('quality')}>Quality</button>
        </div>
      </div>
      <div className="agent-card-grid">
        {agentCards.map((card) => (
          <button className="agent-card" data-testid={`agent-card-${card.title.toLowerCase().replaceAll(' ', '-')}`} key={card.title} onClick={cardActions[card.title]}>
            <span className={`agent-icon ${card.tone}`}>{card.icon}</span>
            <strong>{card.title}</strong>
            <p>{card.copy}</p>
          </button>
        ))}
      </div>
      <SystemImageStrip systemImage={systemImage} project={project} />
      {pendingGoal ? (
        <div className="confirmation-gate-card" data-testid="agent-confirmation-gate">
          <div>
            <span className="confirmation-kicker">Confirmation required</span>
            <strong>{pendingGoal.title}</strong>
            <p>The agent paused before a high-risk tool. Confirm in conversation to continue the same audited tool chain.</p>
          </div>
          <button className="composer-action-button build-submit-button" data-testid="confirm-agent-goal" onClick={confirmPendingGoal} disabled={loading}>
            {loading ? 'Continuing...' : 'Confirm and continue'}
          </button>
        </div>
      ) : null}
      <div className="agent-log">
        {messages.slice(-5).map((message, index) => (
          <div className={`message-row ${message.role}`} key={`${message.role}-${message.text}-${index}`}>
            <span>{message.role === 'user' ? 'You' : message.role === 'tool' ? 'Tool' : 'Nasus'}</span>
            <p>{message.text}</p>
          </div>
        ))}
      </div>
      <div className="task-composer">
        <textarea
          data-testid="project-agent-input"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Start typing a prompt to see what our agents can do"
        />
        <div className="task-chip-row">
          <button className="tool-chip">Tools</button>
          <button className="tool-chip active" data-testid="tool-system-image" onClick={initializeSystemImage}>System image ×</button>
          <button className="tool-chip active" onClick={() => askProject('Continue the quality loop for the riskiest open US.')}>Quality loop ×</button>
          <button className="tool-chip" onClick={() => askProject('Assess release gate readiness and list blockers.')}>Release gate</button>
          <button className="round-icon" data-testid="project-agent-submit" onClick={runPrompt} disabled={loading}>↵</button>
        </div>
      </div>
    </section>
  )
}

function SystemImageStrip({ systemImage, project }: { systemImage?: SystemImageData; project: ProjectCard }) {
  const sourceCount = systemImage?.sources.length ?? 0
  const indexed = systemImage?.sources.filter((source) => source.ingestion_status === 'indexed').length ?? 0
  const metricGroups = systemImage?.metric_snapshots.map((metric) => metric.metric_group) ?? []

  return (
    <div className="system-image-strip" data-testid="system-image-strip">
      <div>
        <span className="eyebrow">System image</span>
        <strong>{project.system_image_status}</strong>
        <p>{systemImage?.summary ?? 'Waiting for source ingestion and baseline initialization.'}</p>
      </div>
      <div className="source-stat-grid">
        <MetricMini label="Sources indexed" value={`${indexed}/${sourceCount || 3}`} />
        <MetricMini label="Objects" value={`${systemImage?.objects.length ?? 0}`} />
        <MetricMini label="Relations" value={`${systemImage?.relationships.length ?? 0}`} />
        <MetricMini label="Metrics" value={`${metricGroups.length}`} />
      </div>
    </div>
  )
}

function MetricMini({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-mini">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function RunSettingsPanel({ project, systemImage }: { project?: ProjectCard; systemImage?: SystemImageData }) {
  const codeSource = systemImage?.sources.find((source) => source.source_type === 'code')
  const usSource = systemImage?.sources.find((source) => source.source_type === 'us_doc')
  const testSource = systemImage?.sources.find((source) => source.source_type === 'test_asset')

  return (
    <aside className="run-panel">
      <div className="run-panel-header">
        <span>Run settings</span>
        <button>⌘ Get code</button>
        <button>×</button>
      </div>
      <div className="settings-card featured">
        <strong>Nasus Quality Agent</strong>
        <span>agent-first-quality-v1</span>
        <p>Autonomous quality agent running on the project tool catalog and governed workflow gates.</p>
      </div>
      <div className="settings-card">
        <strong>System instructions</strong>
        <p>Use system image evidence, cite source refs, and never write official baseline without approval.</p>
      </div>
      <div className="panel-section">
        <div className="panel-section-title">Tools</div>
        <ToggleRow label="Code analysis" active={codeSource?.ingestion_status === 'indexed'} />
        <ToggleRow label="US document parser" active={usSource?.ingestion_status === 'indexed'} />
        <ToggleRow label="Test asset ingestion" active={testSource?.ingestion_status === 'indexed'} />
        <ToggleRow label="Release gate" active={false} />
      </div>
      <div className="panel-section">
        <div className="panel-section-title">Project</div>
        <p className="panel-copy">{project?.name ?? 'No project selected'} · System image {project?.system_image_status ?? 'draft'}</p>
      </div>
      <div className="panel-section">
        <div className="panel-section-title">Quality metrics</div>
        {(systemImage?.metric_snapshots ?? []).map((metric) => (
          <div className="metric-row" key={metric.id}>
            <span>{metric.metric_group.replaceAll('_', ' ')}</span>
            <strong>{Object.keys(metric.metrics).length}</strong>
          </div>
        ))}
      </div>
    </aside>
  )
}

function SettingsPopover({
  settings,
  testing,
  testResult,
  onTheme,
  onLanguage,
  onNotification,
  onSaveModel,
  onTestModel,
}: {
  settings?: StudioSettings
  testing: boolean
  testResult?: SettingsConnectionResult
  onTheme: (theme: 'dark' | 'light' | 'system') => void
  onLanguage: (language: 'en' | 'zh') => void
  onNotification: (notificationMode: 'important' | 'all' | 'muted') => void
  onSaveModel: (payload: Record<string, unknown>) => void
  onTestModel: (payload: StudioSettingsConnectionTestRequest) => void
}) {
  type SettingsPanel = 'theme' | 'language' | 'model' | 'notifications' | 'account' | 'status'
  const [activePanel, setActivePanel] = useState<SettingsPanel>('theme')
  const [activeRoute, setActiveRoute] = useState<ModelRoute>('chat')
  const activeProfile = profileFor(settings, activeRoute)
  const [modelPreset, setModelPreset] = useState(activeProfile.model_preset)
  const [providerKind, setProviderKind] = useState<CustomModelConfig['provider_kind']>(activeProfile.custom_model.provider_kind)
  const [baseUrl, setBaseUrl] = useState(activeProfile.custom_model.base_url ?? '')
  const [modelName, setModelName] = useState(activeProfile.custom_model.model_name)
  const [apiKey, setApiKey] = useState('')

  useEffect(() => {
    const profile = profileFor(settings, activeRoute)
    setModelPreset(profile.model_preset)
    setProviderKind(profile.custom_model.provider_kind)
    setBaseUrl(profile.custom_model.base_url ?? '')
    setModelName(profile.custom_model.model_name)
    setApiKey('')
  }, [activeRoute, settings])

  const maskedKey = activeProfile.custom_model.api_key_masked
  const status = activeProfile.active_provider_status
  const savePayload = {
    model_route: activeRoute,
    model_preset: modelPreset,
    custom_provider_kind: providerKind,
    custom_base_url: baseUrl,
    custom_model_name: modelName,
    ...(apiKey.trim() ? { custom_api_key: apiKey.trim() } : {}),
  }
  const testPayload: StudioSettingsConnectionTestRequest = {
    model_route: activeRoute,
    model_preset: modelPreset,
    custom_provider_kind: providerKind,
    custom_base_url: baseUrl,
    custom_model_name: modelName,
    ...(apiKey.trim() ? { custom_api_key: apiKey.trim() } : {}),
  }

  const menuItems: Array<{
    id?: SettingsPanel
    icon: string
    label: string
    value?: string
    separator?: boolean
  }> = [
    { id: 'theme', icon: '◌', label: 'Theme', value: settings?.theme ?? 'dark' },
    { id: 'language', icon: 'A', label: 'Language', value: settings?.language === 'zh' ? '中文' : 'English' },
    { id: 'model', icon: '◇', label: 'Model configuration', value: activeRoute === 'chat' ? 'LLM' : activeRoute },
    { id: 'notifications', icon: '◍', label: 'Applet notifications', value: settings?.notification_mode ?? 'important' },
    { id: 'account', icon: '◎', label: 'Account status', separator: true },
    { id: 'status', icon: '≋', label: 'View status' },
    { icon: '□', label: 'Terms of service' },
    { icon: '▱', label: 'Privacy policy' },
    { icon: '↗', label: 'Send feedback' },
    { icon: '◉', label: 'Billing Support' },
  ]

  function renderPanel() {
    if (activePanel === 'theme') {
      return (
        <div className="settings-submenu settings-submenu-compact">
          {(['light', 'dark', 'system'] as const).map((theme) => (
            <button className={settings?.theme === theme ? 'selected' : ''} key={theme} onClick={() => onTheme(theme)} type="button">
              <span>{settings?.theme === theme ? '●' : '○'}</span>
              <span>{theme === 'light' ? 'Light' : theme === 'dark' ? 'Dark' : 'System'}</span>
            </button>
          ))}
        </div>
      )
    }

    if (activePanel === 'language') {
      return (
        <div className="settings-submenu settings-submenu-compact">
          {(['en', 'zh'] as const).map((language) => (
            <button className={settings?.language === language ? 'selected' : ''} key={language} onClick={() => onLanguage(language)} type="button">
              <span>{settings?.language === language ? '●' : '○'}</span>
              <span>{language === 'en' ? 'English' : '中文'}</span>
            </button>
          ))}
        </div>
      )
    }

    if (activePanel === 'notifications') {
      return (
        <div className="settings-submenu settings-submenu-compact">
          {(['important', 'all', 'muted'] as const).map((mode) => (
            <button className={settings?.notification_mode === mode ? 'selected' : ''} key={mode} onClick={() => onNotification(mode)} type="button">
              <span>{settings?.notification_mode === mode ? '●' : '○'}</span>
              <span>{mode === 'important' ? 'Important only' : mode === 'all' ? 'All notifications' : 'Muted'}</span>
            </button>
          ))}
        </div>
      )
    }

    if (activePanel === 'account') {
      return (
        <div className="settings-submenu settings-submenu-info">
          <div className="settings-submenu-title">Account status</div>
          <div className="settings-info-card">
            <strong>uben@example.com</strong>
            <span>Local development workspace</span>
          </div>
          <div className="settings-info-card">
            <strong>Agent-first mode</strong>
            <span>All write actions should route through tool invocations.</span>
          </div>
        </div>
      )
    }

    if (activePanel === 'status') {
      return (
        <div className="settings-submenu settings-submenu-info">
          <div className="settings-submenu-title">Provider status</div>
          {(['chat', 'embedding', 'rerank'] as ModelRoute[]).map((route) => {
            const profile = profileFor(settings, route)
            return (
              <div className="settings-info-card" key={route}>
                <strong>{route === 'chat' ? 'LLM' : route}</strong>
                <span>{profile.model_provider} · {profile.model_name}</span>
                <span className={`settings-provider-pill ${profile.runtime_mode === 'live' ? 'live' : 'fallback'}`}>{profile.runtime_mode}</span>
              </div>
            )
          })}
        </div>
      )
    }

    return (
      <div className="settings-submenu settings-model-submenu">
        <div className="settings-submenu-title">Model configuration</div>
        <div className="model-route-tabs">
          {(['chat', 'embedding', 'rerank'] as ModelRoute[]).map((route) => (
            <button className={activeRoute === route ? 'active' : ''} key={route} onClick={() => setActiveRoute(route)} type="button">
              {route === 'chat' ? 'LLM' : route}
            </button>
          ))}
        </div>
        <div className="settings-provider-banner compact">
          <span className={`settings-provider-pill ${activeProfile.runtime_mode === 'live' ? 'live' : 'fallback'}`}>
            {activeProfile.runtime_mode}
          </span>
          <span className="settings-provider-copy">{status.reason}</span>
        </div>
        <div className="model-config-form">
          <label className="settings-field">
            <span className="settings-field-label">Route mode</span>
            <select className="settings-field-control" value={modelPreset} onChange={(event) => setModelPreset(event.target.value as 'system_default' | 'custom')}>
              <option value="system_default">System default</option>
              <option value="custom">Custom provider</option>
            </select>
          </label>
          <label className="settings-field">
            <span className="settings-field-label">Provider</span>
            <select className="settings-field-control" value={providerKind} onChange={(event) => setProviderKind(event.target.value as CustomModelConfig['provider_kind'])}>
              <option value="openai_compatible">OpenAI compatible</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </label>
          <label className="settings-field">
            <span className="settings-field-label">Base URL</span>
            <input className="settings-field-control" placeholder="https://api.example.com/v1" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </label>
          <label className="settings-field">
            <span className="settings-field-label">Model</span>
            <input className="settings-field-control" placeholder={activeRoute === 'embedding' ? 'text-embedding-3-large' : activeRoute === 'rerank' ? 'rerank-model' : 'gpt-5.4'} value={modelName} onChange={(event) => setModelName(event.target.value)} />
          </label>
          <label className="settings-field">
            <span className="settings-field-label">API Key</span>
            <input className="settings-field-control" type="password" placeholder={maskedKey ? `Saved ${maskedKey}` : 'Paste API key'} value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
          </label>
          <div className="settings-form-actions">
            <button className="settings-save-button secondary" disabled={testing} onClick={() => onTestModel(testPayload)} type="button">
              {testing ? 'Testing...' : 'Test connection'}
            </button>
            <button className="settings-save-button" onClick={() => onSaveModel(savePayload)} type="button">
              Save {activeRoute}
            </button>
          </div>
        </div>
        {testResult ? (
          <div className={`settings-test-result ${testResult.ok ? 'success' : 'warning'}`}>
            <strong>{testResult.model_route ?? activeRoute} · {testResult.runtime_mode}</strong>
            <span>{testResult.message}</span>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="settings-pop">
      <div className="settings-menu">
        {menuItems.map((item) => (
          <button
            className={`${item.id === activePanel ? 'active' : ''} ${item.separator ? 'with-separator' : ''}`}
            key={item.label}
            onClick={() => item.id ? setActivePanel(item.id) : undefined}
            type="button"
          >
            <span className="settings-menu-icon">{item.icon}</span>
            <span className="settings-menu-label">{item.label}</span>
            {item.value ? <span className="settings-menu-value">{item.value}</span> : null}
            {item.id ? <span className="settings-menu-chevron">›</span> : null}
          </button>
        ))}
      </div>
      {renderPanel()}
    </div>
  )
}

function profileFor(settings: StudioSettings | undefined, route: ModelRoute) {
  const fallback = {
    route,
    model_preset: 'system_default' as const,
    model_provider: 'openai' as const,
    model_name: route === 'embedding' ? 'text-embedding-3-large' : route === 'rerank' ? 'nasus-rerank-system-default' : 'gpt-5.4',
    runtime_mode: 'fallback' as const,
    fallback_provider: 'mock' as const,
    provider_statuses: [],
    active_provider_status: {
      provider: 'openai' as const,
      available: false,
      configured_via: 'system_default' as const,
      mode: 'fallback' as const,
      fallback_provider: 'mock' as const,
      reason: 'Settings are loading.',
    },
    custom_model: {
      provider_kind: 'openai_compatible' as const,
      base_url: null,
      model_name: '',
      has_api_key: false,
      api_key_masked: null,
    },
  }
  return settings?.model_profiles?.[route] ?? fallback
}

function ProjectGallery({ projects, openProject }: { projects: ProjectCard[]; openProject: (project: ProjectCard) => void }) {
  return (
    <div className="project-gallery">
      {projects.map((project) => (
        <button className="project-card-ai" data-testid="project-card" key={project.id} onClick={() => openProject(project)}>
          <div className="project-card-top">
            <span className="project-code">{project.code}</span>
            <span className={`risk-pill ${project.risk}`}>{project.risk}</span>
          </div>
          <strong>{project.name}</strong>
          <p>{project.summary}</p>
          <div className="progress-track"><span style={{ width: `${project.progress}%` }} /></div>
          <div className="project-meta">
            <span>{project.active_version}</span>
            <span>{project.progress}%</span>
          </div>
        </button>
      ))}
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function DocCard({ title, copy }: { title: string; copy: string }) {
  return (
    <article className="doc-card">
      <span>Documentation</span>
      <h3>{title}</h3>
      <p>{copy}</p>
    </article>
  )
}

function ToggleRow({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="toggle-row">
      <span>{label}</span>
      <span className={`toggle ${active ? 'on' : ''}`}><i /></span>
    </div>
  )
}
