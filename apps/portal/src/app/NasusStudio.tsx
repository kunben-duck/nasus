import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'

import { api } from '../features/api'
import type {
  AgentGoal,
  ConversationSession,
  CustomModelConfig,
  ModelRoute,
  ProjectCard,
  ProjectWorkspaceData,
  SettingsConnectionResult,
  StudioSettings,
  StudioSettingsConnectionTestRequest,
  SystemImageData,
  ToolInvocation,
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
type BackendStatus = 'loading' | 'live' | 'offline'

function routeStateFromPath(pathname: string): { view: StudioView; projectId: string | null } {
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/)
  if (projectMatch?.[1]) {
    return { view: 'project', projectId: decodeURIComponent(projectMatch[1]) }
  }
  if (pathname.startsWith('/dashboard')) return { view: 'dashboard', projectId: null }
  if (pathname.startsWith('/documentation')) return { view: 'documentation', projectId: null }
  return { view: 'build', projectId: null }
}

function pathForView(view: StudioView, projectId?: string | null) {
  if (view === 'dashboard') return '/dashboard'
  if (view === 'documentation') return '/documentation'
  if (view === 'project' && projectId) return `/projects/${encodeURIComponent(projectId)}`
  return '/build'
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
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const routeState = useMemo(() => routeStateFromPath(location.pathname), [location.pathname])
  const [view, setViewState] = useState<StudioView>(routeState.view)
  const [activeProjectId, setActiveProjectIdState] = useState<string | null>(routeState.projectId)
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
  const backendStatus: BackendStatus = useMemo(() => {
    if (settingsQuery.isLoading || dashboardQuery.isLoading || buildQuery.isLoading) return 'loading'
    if (settingsQuery.isError || dashboardQuery.isError || buildQuery.isError) return 'offline'
    return 'live'
  }, [
    buildQuery.isError,
    buildQuery.isLoading,
    dashboardQuery.isError,
    dashboardQuery.isLoading,
    settingsQuery.isError,
    settingsQuery.isLoading,
  ])
  const settingsDisabled = backendStatus !== 'live' || !settingsQuery.data

  useEffect(() => {
    setViewState(routeState.view)
    if (routeState.projectId) {
      setActiveProjectIdState(routeState.projectId)
    }
  }, [routeState.projectId, routeState.view])

  const setView = useCallback(
    (nextView: StudioView) => {
      setViewState(nextView)
      const nextPath = pathForView(nextView, activeProjectId)
      if (location.pathname !== nextPath) {
        navigate(nextPath)
      }
    },
    [activeProjectId, location.pathname, navigate],
  )

  const openProjectRoute = useCallback(
    (projectId: string) => {
      setActiveProjectIdState(projectId)
      setViewState('project')
      const nextPath = pathForView('project', projectId)
      if (location.pathname !== nextPath) {
        navigate(nextPath)
      }
    },
    [location.pathname, navigate],
  )

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
  const projectWorkspaceQuery = useQuery({
    queryKey: ['project', activeProject?.id],
    queryFn: () => api.getProject(activeProject!.id),
    enabled: Boolean(activeProject?.id),
  })

  const visibleMessages = useMemo(() => {
    const conversation = view === 'project' ? projectConversation.conversation : buildConversation.conversation
    const rows = toMessageRows(conversation)
    return rows.length ? rows : fallbackMessages
  }, [buildConversation.conversation, fallbackMessages, projectConversation.conversation, view])
  const pausedProjectGoal = useMemo(
    () => projectConversation.conversation?.agent_goals.find((goal) => goal.status === 'paused'),
    [projectConversation.conversation],
  )
  const latestProjectGoal = projectConversation.conversation?.agent_goals.at(-1)

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
      return api.postMessage(
        conversation.id,
        'Build the official system image from code, historical US documents, and historical test assets.',
      )
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
          await queryClient.invalidateQueries({ queryKey: ['project', activeProject.id] })
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
        openProjectRoute(created.id)
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
    openProjectRoute(project.id)
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
        await queryClient.invalidateQueries({ queryKey: ['project', activeProject.id] })
        await queryClient.invalidateQueries({ queryKey: ['system-image', activeProject.id] })
        await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      }
    } finally {
      setPrompt('')
      setIsPromptRunning(false)
    }
  }

  async function invokeProjectTool(toolId: string, input: Record<string, unknown> = {}) {
    if (!activeProject) return
    setIsPromptRunning(true)
    try {
      const conversation = await api.ensureConversation('project', activeProject.id, activeProject.name)
      await api.invokeTool({
        conversation_id: conversation.id,
        tool_id: toolId,
        input: {
          project_id: activeProject.id,
          ...input,
        },
        initiator_surface: 'ui',
        initiator_actor: 'user',
      })
      await queryClient.invalidateQueries({ queryKey: ['project', activeProject.id] })
      await queryClient.invalidateQueries({ queryKey: ['system-image', activeProject.id] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      await queryClient.invalidateQueries({ queryKey: ['conversation', conversation.id] })
    } finally {
      setIsPromptRunning(false)
    }
  }

  async function confirmPendingGoal() {
    if (!pausedProjectGoal || pausedProjectGoal.pause_reason !== 'waiting_confirmation') return
    setIsPromptRunning(true)
    try {
      await projectConversation.sendMessage('确认，继续执行')
      if (activeProject) {
        await queryClient.invalidateQueries({ queryKey: ['project', activeProject.id] })
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
          <BackendStatusPill status={backendStatus} />
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
            project={projectWorkspaceQuery.data?.project ?? activeProject}
            workspace={projectWorkspaceQuery.data}
            systemImage={systemImageQuery.data}
            mode={agentMode}
            setMode={setAgentMode}
            messages={visibleMessages}
            agentGoal={latestProjectGoal}
            toolInvocations={projectConversation.conversation?.tool_invocations ?? []}
            pendingGoal={pausedProjectGoal}
            prompt={prompt}
            setPrompt={setPrompt}
            runPrompt={runPrompt}
            askProject={askProject}
            invokeProjectTool={invokeProjectTool}
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
          disabled={settingsDisabled}
          statusMessage={
            backendStatus === 'loading'
              ? 'Settings are loading from the backend.'
              : backendStatus === 'offline'
                ? 'Backend is offline. Configuration is read-only preview and cannot be persisted.'
                : 'Settings are connected to the backend and will be persisted securely.'
          }
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
  workspace,
  systemImage,
  mode,
  setMode,
  messages,
  agentGoal,
  toolInvocations,
  pendingGoal,
  prompt,
  setPrompt,
  runPrompt,
  askProject,
  invokeProjectTool,
  confirmPendingGoal,
  initializeSystemImage,
  loading,
  sidebarCollapsed,
  toggleSidebar,
}: {
  project: ProjectCard
  workspace?: ProjectWorkspaceData
  systemImage?: SystemImageData
  mode: AgentMode
  setMode: (mode: AgentMode) => void
  messages: MessageRow[]
  agentGoal?: AgentGoal
  toolInvocations: ToolInvocation[]
  pendingGoal?: AgentGoal
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  askProject: (promptText: string) => void
  invokeProjectTool: (toolId: string, input?: Record<string, unknown>) => void
  confirmPendingGoal: () => void
  initializeSystemImage: () => void
  loading: boolean
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}) {
  const cardActions: Record<string, () => void> = {
    'System Image Builder': initializeSystemImage,
    'Quality Loop Agent': () => askProject('Continue the quality loop for the riskiest open US.'),
    'Release Assessor': () => invokeProjectTool('release.assess'),
    'Repo Maintainer': () => invokeProjectTool('query.system_image.status'),
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
      <AgentGoalPanel goal={agentGoal} />
      <ToolInvocationRail invocations={toolInvocations} />
      <QualityAssetPanel workspace={workspace} />
      {pendingGoal ? (
        <div className="confirmation-gate-card" data-testid="agent-confirmation-gate">
          <div>
            <span className="confirmation-kicker">
              {pendingGoal.pause_reason === 'missing_source_binding' ? 'Source bindings required' : 'Confirmation required'}
            </span>
            <strong>{pendingGoal.title}</strong>
            <p>
              {pendingGoal.pause_reason === 'missing_source_binding'
                ? 'Provide code path, historical US documents path, and historical test assets path to continue the same audited tool chain.'
                : 'The agent paused before a high-risk tool. Confirm in conversation to continue the same audited tool chain.'}
            </p>
          </div>
          {pendingGoal.pause_reason === 'waiting_confirmation' ? (
            <button className="composer-action-button build-submit-button" data-testid="confirm-agent-goal" onClick={confirmPendingGoal} disabled={loading}>
              {loading ? 'Continuing...' : 'Confirm and continue'}
            </button>
          ) : null}
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
          <button className="tool-chip" data-testid="tool-release-gate" onClick={() => invokeProjectTool('release.assess')}>Release gate</button>
          <button className="round-icon" data-testid="project-agent-submit" onClick={runPrompt} disabled={loading}>↵</button>
        </div>
      </div>
    </section>
  )
}

function ToolInvocationRail({ invocations }: { invocations: ToolInvocation[] }) {
  const visibleInvocations = invocations
    .filter((invocation) => ['pending', 'running', 'waiting_confirmation', 'waiting_approval', 'completed', 'failed'].includes(invocation.status))
    .slice(-4)

  if (!visibleInvocations.length) return null

  return (
    <div className="tool-invocation-rail" data-testid="tool-invocation-rail">
      <div className="tool-invocation-heading">
        <span className="eyebrow">Tool runtime</span>
        <strong>Agent actions</strong>
      </div>
      <div className="tool-invocation-list">
        {visibleInvocations.map((invocation) => (
          <div className={`tool-invocation-pill ${invocation.status}`} key={invocation.id}>
            <span className="tool-invocation-dot" aria-hidden="true" />
            <span className="tool-invocation-name">{invocation.tool_id}</span>
            <span className="tool-invocation-status">{invocation.status.replaceAll('_', ' ')}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function QualityAssetPanel({ workspace }: { workspace?: ProjectWorkspaceData }) {
  const lanes = workspace?.asset_lanes ?? []
  const primaryUs = workspace?.us_items[0]
  const latestRun = workspace?.runs[0]
  const qualityState = workspace?.quality_loop_state
  const qualityStages = ['Scenarios', 'Cases', 'Automation', 'Release']

  if (!workspace) {
    return null
  }

  return (
    <div className="quality-asset-panel" data-testid="quality-asset-panel">
      <div className="quality-panel-header">
        <div>
          <span className="eyebrow">Quality loop</span>
          <strong>{primaryUs?.title ?? 'Waiting for US work item'}</strong>
          <p>{primaryUs ? `${primaryUs.status} · ${primaryUs.progress}% · ${primaryUs.next_action}` : 'Import US documents or build the system image to create the first work item.'}</p>
        </div>
        {qualityState ? (
          <span className={`quality-state-pill ${qualityState.status}`}>{qualityState.status.replaceAll('_', ' ')}</span>
        ) : latestRun ? (
          <span className={`run-status-pill ${latestRun.status}`}>{latestRun.status}</span>
        ) : null}
      </div>
      {qualityState ? (
        <div className="quality-loop-state-card" data-testid="quality-loop-state">
          <div>
            <strong>{qualityState.label}</strong>
            <p>
              Release score {qualityState.release_score || 0} · Next tool{' '}
              {qualityState.next_recommended_tools[0] ?? 'none'}
            </p>
          </div>
          <div className="quality-stage-bar" aria-label="Quality loop stage">
            {qualityStages.map((stage, index) => {
              const active = qualityState.stage_index >= index + 1
              return (
                <span className={active ? 'active' : ''} key={stage}>
                  <i />
                  {stage}
                </span>
              )
            })}
          </div>
          {qualityState.blockers.length ? (
            <div className="quality-blocker-list">
              {qualityState.blockers.map((blocker) => <span key={blocker}>{blocker}</span>)}
            </div>
          ) : null}
        </div>
      ) : null}
      {lanes.length ? (
        <div className="quality-lane-grid">
          {lanes.map((lane) => (
            <div className={`quality-lane-card ${lane.status}`} key={lane.id}>
              <div>
                <span className="quality-lane-dot" />
                <strong>{lane.label}</strong>
              </div>
              <p>{lane.summary}</p>
              <span>{lane.status}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="quality-empty-state">
          No quality asset lanes yet. Ask Nasus to build the system image or import US documents first.
        </div>
      )}
      {latestRun ? (
        <div className="quality-run-row">
          <span>Latest run</span>
          <strong>{latestRun.title}</strong>
          <p>{latestRun.summary}</p>
        </div>
      ) : null}
    </div>
  )
}

function AgentGoalPanel({ goal }: { goal?: AgentGoal }) {
  if (!goal) return null

  const visibleSteps = goal.steps
    .filter((step) => step.phase || step.selected_tool_id || step.status !== 'pending')
    .slice(-9)
  const totalSteps = goal.steps.length || goal.max_steps || 1
  const completedSteps = goal.steps.filter((step) => step.status === 'completed').length
  const currentStep = [...visibleSteps].reverse().find((step) => step.status === 'running' || step.status === 'blocked') ?? visibleSteps.at(-1)
  const detailSteps = visibleSteps.slice(-5)

  return (
    <div className="agent-goal-panel" data-testid="agent-goal-panel">
      <div className="agent-goal-summary">
        <span className={`agent-goal-status ${goal.status}`}>{goal.status}</span>
        <div>
          <strong>{goal.title}</strong>
          <p>{goal.summary}</p>
        </div>
        <span className="agent-goal-progress">{completedSteps}/{totalSteps}</span>
      </div>
      {currentStep ? (
        <div className="agent-current-step" data-testid="agent-current-step">
          <div>
            <span className="eyebrow">Current agent step</span>
            <strong>{currentStep.title}</strong>
            <p>{agentStepNarrative(currentStep)}</p>
          </div>
          <span className={`agent-phase-pill ${currentStep.phase ?? currentStep.status}`}>
            {currentStep.phase ?? currentStep.status}
          </span>
        </div>
      ) : null}
      <div className="agent-step-rail">
        {visibleSteps.map((step) => (
          <div className={`agent-step-pill ${step.status}`} key={step.id}>
            <span className="agent-step-dot" />
            <span className="agent-step-label">{step.selected_tool_id ?? step.phase ?? step.title}</span>
            <span className="agent-step-status">{step.status}</span>
          </div>
        ))}
      </div>
      {detailSteps.length ? (
        <div className="agent-loop-trace" data-testid="agent-loop-trace">
          <div className="agent-loop-trace-header">
            <span className="eyebrow">Agent loop trace</span>
            <strong>Think · Act · Observe · Decide</strong>
          </div>
          <div className="agent-loop-card-grid">
            {detailSteps.map((step) => (
              <div className={`agent-loop-card ${step.status}`} key={`${step.id}-detail`}>
                <div className="agent-loop-card-head">
                  <span>{step.phase ?? 'step'}</span>
                  <strong>{step.selected_tool_id ?? step.title}</strong>
                </div>
                <p>{agentStepNarrative(step)}</p>
                <div className="agent-loop-card-meta">
                  {step.tool_invocation_id ? <span>tool {step.tool_invocation_id}</span> : null}
                  {step.memory_recent_turn_count ? <span>{step.memory_recent_turn_count} turns</span> : null}
                  {step.decision ? <span>decision {step.decision}</span> : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function agentStepNarrative(step: AgentGoal['steps'][number]) {
  if (step.reasoning) return step.reasoning
  if (step.observation_summary) return step.observation_summary
  if (step.decision_rationale) return step.decision_rationale
  if (step.selected_tool_id) return `Executing ${step.selected_tool_id} through the canonical tool runtime.`
  if (step.next_plan_hint) return `Next recommended tool: ${step.next_plan_hint}.`
  return step.status === 'running' ? 'Agent is processing this step.' : 'Step is recorded in the agent loop trace.'
}

function SystemImageStrip({ systemImage, project }: { systemImage?: SystemImageData; project: ProjectCard }) {
  const sourceCount = systemImage?.sources.length ?? 0
  const indexed = systemImage?.sources.filter((source) => source.ingestion_status === 'indexed').length ?? 0
  const metricGroups = systemImage?.metric_snapshots.map((metric) => metric.metric_group) ?? []
  const status = systemImage?.project.system_image_status ?? project.system_image_status
  const buildState = systemImage?.build_state
  const stages = ['Sources', 'Ingest', 'Index', 'Context', 'Baseline']

  return (
    <div className="system-image-strip" data-testid="system-image-strip">
      <div>
        <span className="eyebrow">System image</span>
        <div className="system-image-title-row">
          <strong>{status}</strong>
          {buildState ? <span className={`system-image-state ${buildState.status}`}>{buildState.status.replaceAll('_', ' ')}</span> : null}
        </div>
        <p>{systemImage?.summary ?? 'Waiting for source ingestion and baseline initialization.'}</p>
        {buildState ? <div className="system-image-build-label">{buildState.label}</div> : null}
        {buildState ? (
          <div className="system-image-stage-bar" aria-label="System image build state">
            {stages.map((stage, index) => {
              const stageNumber = index + 1
              const active = buildState.stage_index >= stageNumber
              return (
                <span className={active ? 'active' : ''} key={stage}>
                  <i />
                  {stage}
                </span>
              )
            })}
          </div>
        ) : null}
        {buildState?.missing_source_types.length ? (
          <div className="system-image-hint">
            Missing sources: {buildState.missing_source_types.join(', ')}
          </div>
        ) : null}
        {buildState?.failed_source_ids.length ? (
          <div className="system-image-hint failed">
            Failed sources: {buildState.failed_source_ids.join(', ')}
          </div>
        ) : null}
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

function BackendStatusPill({ status }: { status: BackendStatus }) {
  const label = status === 'live' ? 'Live' : status === 'loading' ? 'Connecting' : 'Offline preview'
  const copy = status === 'live'
    ? 'Backend connected'
    : status === 'loading'
      ? 'Checking backend'
      : 'Using local preview data'

  return (
    <span className={`backend-status-pill ${status}`} title={copy} data-testid="backend-status-pill">
      <span className="backend-status-dot" />
      <span>{label}</span>
    </span>
  )
}

function SettingsPopover({
  settings,
  disabled,
  statusMessage,
  testing,
  testResult,
  onTheme,
  onLanguage,
  onNotification,
  onSaveModel,
  onTestModel,
}: {
  settings?: StudioSettings
  disabled: boolean
  statusMessage: string
  testing: boolean
  testResult?: SettingsConnectionResult
  onTheme: (theme: 'dark' | 'light' | 'system') => void
  onLanguage: (language: 'en' | 'zh') => void
  onNotification: (notificationMode: 'important' | 'all' | 'muted') => void
  onSaveModel: (payload: Record<string, unknown>) => void
  onTestModel: (payload: StudioSettingsConnectionTestRequest) => void
}) {
  type SettingsPanel = 'theme' | 'language' | 'model' | 'notifications' | 'account' | 'status'
  type ModelDraft = {
    modelPreset: StudioSettings['model_preset']
    providerKind: CustomModelConfig['provider_kind']
    baseUrl: string
    modelName: string
    apiKey: string
  }
  const [activePanel, setActivePanel] = useState<SettingsPanel>('theme')
  const [activeRoute, setActiveRoute] = useState<ModelRoute>('chat')
  const [modelDrafts, setModelDrafts] = useState<Partial<Record<ModelRoute, Partial<ModelDraft>>>>({})
  const activeProfile = profileFor(settings, activeRoute)
  const modelDraft = modelDrafts[activeRoute]
  const modelPreset = modelDraft?.modelPreset ?? activeProfile.model_preset
  const providerKind = modelDraft?.providerKind ?? activeProfile.custom_model.provider_kind
  const baseUrl = modelDraft?.baseUrl ?? activeProfile.custom_model.base_url ?? ''
  const modelName = modelDraft?.modelName ?? activeProfile.custom_model.model_name
  const apiKey = modelDraft?.apiKey ?? ''

  function updateModelDraft(patch: Partial<ModelDraft>) {
    setModelDrafts((current) => ({
      ...current,
      [activeRoute]: {
        ...current[activeRoute],
        ...patch,
      },
    }))
  }

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
            <button className={settings?.theme === theme ? 'selected' : ''} disabled={disabled} key={theme} onClick={() => onTheme(theme)} type="button">
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
            <button className={settings?.language === language ? 'selected' : ''} disabled={disabled} key={language} onClick={() => onLanguage(language)} type="button">
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
            <button className={settings?.notification_mode === mode ? 'selected' : ''} disabled={disabled} key={mode} onClick={() => onNotification(mode)} type="button">
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
        <div className={`settings-provider-banner compact ${disabled ? 'readonly' : ''}`}>
          <span className={`settings-provider-pill ${disabled ? 'fallback' : 'live'}`}>
            {disabled ? 'read only' : 'connected'}
          </span>
          <span className="settings-provider-copy">{statusMessage}</span>
        </div>
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
            <select className="settings-field-control" disabled={disabled} value={modelPreset} onChange={(event) => updateModelDraft({ modelPreset: event.target.value as 'system_default' | 'custom' })}>
              <option value="system_default">System default</option>
              <option value="custom">Custom provider</option>
            </select>
          </label>
          <label className="settings-field">
            <span className="settings-field-label">Provider</span>
            <select className="settings-field-control" disabled={disabled} value={providerKind} onChange={(event) => updateModelDraft({ providerKind: event.target.value as CustomModelConfig['provider_kind'] })}>
              <option value="openai_compatible">OpenAI compatible</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </label>
          <label className="settings-field">
            <span className="settings-field-label">Base URL</span>
            <input className="settings-field-control" disabled={disabled} placeholder="https://api.example.com/v1" value={baseUrl} onChange={(event) => updateModelDraft({ baseUrl: event.target.value })} />
          </label>
          <label className="settings-field">
            <span className="settings-field-label">Model</span>
            <input className="settings-field-control" disabled={disabled} placeholder={activeRoute === 'embedding' ? 'text-embedding-3-large' : activeRoute === 'rerank' ? 'rerank-model' : 'gpt-5.4'} value={modelName} onChange={(event) => updateModelDraft({ modelName: event.target.value })} />
          </label>
          <label className="settings-field">
            <span className="settings-field-label">API Key</span>
            <input className="settings-field-control" disabled={disabled} type="password" placeholder={maskedKey ? `Saved ${maskedKey}` : 'Paste API key'} value={apiKey} onChange={(event) => updateModelDraft({ apiKey: event.target.value })} />
          </label>
          <div className="settings-form-actions">
            <button className="settings-save-button secondary" disabled={disabled || testing} onClick={() => onTestModel(testPayload)} type="button">
              {testing ? 'Testing...' : 'Test connection'}
            </button>
            <button className="settings-save-button" disabled={disabled} onClick={() => onSaveModel(savePayload)} type="button">
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
