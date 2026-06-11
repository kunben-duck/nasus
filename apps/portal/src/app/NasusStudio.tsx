import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../features/api'
import type { ConversationSession, ProjectCard, StudioSettings, SystemImageData } from '../features/types'
import { useConversation } from '../hooks/useConversation'

type StudioView = 'build' | 'dashboard' | 'documentation' | 'project'
type AgentMode = 'planning' | 'sources' | 'quality'
type MessageRow = { role: 'assistant' | 'user' | 'system' | 'tool'; text: string }

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

const sourceChips = [
  'Import Git repository',
  'Import US documents',
  'Import test cases',
  'Import automation scripts',
  'Initialize system image',
  'Assess release quality',
]

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

function useTheme(settings?: StudioSettings) {
  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = settings?.theme ?? 'dark'
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
  const [isPromptRunning, setIsPromptRunning] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: api.getSettings })
  const dashboardQuery = useQuery({ queryKey: ['dashboard'], queryFn: api.getDashboard })
  const buildQuery = useQuery({ queryKey: ['build'], queryFn: api.getBuild })
  const buildConversation = useConversation('build', 'build', 'Build')
  useTheme(settingsQuery.data)

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

  const updateSettings = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.updateSettings(payload),
    onSuccess: (settings) => {
      queryClient.setQueryData(['settings'], settings)
    },
  })

  const initializeSystemImage = useMutation({
    mutationFn: async () => {
      if (!activeProject) return null
      const conversation = await api.ensureConversation('project', activeProject.id, activeProject.name)
      return api.invokeTool({
        conversation_id: conversation.id,
        tool_id: 'baseline.initialize',
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

  const isProjectSpace = view === 'project'

  return (
    <div className="nasus-app">
      <aside className="studio-sidebar">
        <div className="brand-row">
          <div className="brand-mark">N</div>
          <div>
            <div className="brand-name">Nasus Studio</div>
            <div className="brand-kicker">Agent-first QA</div>
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
          <button className="icon-tile">⌁</button>
          <button className="icon-tile" onClick={() => setSettingsOpen((value) => !value)}>⚙</button>
          <button className="icon-tile">⌕</button>
          <button className="icon-tile">⌘</button>
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
          />
        ) : null}
        {isProjectSpace && activeProject ? (
          <ProjectWorkspace
            project={activeProject}
            systemImage={systemImageQuery.data}
            mode={agentMode}
            setMode={setAgentMode}
            messages={visibleMessages}
            prompt={prompt}
            setPrompt={setPrompt}
            runPrompt={runPrompt}
            askProject={askProject}
            initializeSystemImage={() => initializeSystemImage.mutate()}
            loading={isPromptRunning || projectConversation.isSending || initializeSystemImage.isPending}
          />
        ) : null}
      </main>

      {isProjectSpace ? <RunSettingsPanel project={activeProject} systemImage={systemImageQuery.data} /> : null}
      {settingsOpen ? (
        <SettingsPopover
          settings={settingsQuery.data}
          onTheme={(theme) => updateSettings.mutate({ theme })}
          onLanguage={(language) => updateSettings.mutate({ language })}
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
}: {
  view: StudioView
  projects: ProjectCard[]
  openProject: (project: ProjectCard) => void
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  loading: boolean
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
      <button className="collapse-button">☰</button>
      <div className="hero-title">
        <h1>Build quality projects with agents</h1>
        <div className="sparkle" />
      </div>
      <BuildComposer prompt={prompt} setPrompt={setPrompt} runPrompt={runPrompt} loading={loading} />
      <div className="source-chip-row">
        {sourceChips.map((chip) => (
          <button className="source-chip" key={chip}>{chip}</button>
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
}: {
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  loading: boolean
}) {
  return (
    <div className="hero-composer">
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
          <button className="round-icon">⌕</button>
          <button className="round-icon">＋</button>
        </div>
        <button className="lucky-button" data-testid="build-agent-submit" onClick={runPrompt} disabled={loading}>
          ✦ {loading ? 'Building...' : "I'm feeling lucky"}
        </button>
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
  prompt,
  setPrompt,
  runPrompt,
  askProject,
  initializeSystemImage,
  loading,
}: {
  project: ProjectCard
  systemImage?: SystemImageData
  mode: AgentMode
  setMode: (mode: AgentMode) => void
  messages: MessageRow[]
  prompt: string
  setPrompt: (value: string) => void
  runPrompt: () => void
  askProject: (promptText: string) => void
  initializeSystemImage: () => void
  loading: boolean
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
        <button className="collapse-button">☰</button>
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
  onTheme,
  onLanguage,
}: {
  settings?: StudioSettings
  onTheme: (theme: 'dark' | 'light' | 'system') => void
  onLanguage: (language: 'en' | 'zh') => void
}) {
  return (
    <div className="settings-pop">
      <div className="settings-line"><span>Theme</span><strong>{settings?.theme ?? 'dark'}</strong></div>
      <div className="settings-options">
        <button onClick={() => onTheme('light')}>○ Light</button>
        <button onClick={() => onTheme('dark')}>● Dark</button>
        <button onClick={() => onTheme('system')}>○ System</button>
      </div>
      <div className="settings-line"><span>Language</span><strong>{settings?.language ?? 'zh'}</strong></div>
      <div className="settings-options">
        <button onClick={() => onLanguage('en')}>English</button>
        <button onClick={() => onLanguage('zh')}>中文</button>
      </div>
      <div className="settings-line muted"><span>Model</span><strong>{settings?.runtime_mode ?? 'fallback'}</strong></div>
    </div>
  )
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
