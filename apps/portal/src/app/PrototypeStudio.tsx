import { Fragment, useEffect, useMemo, useState } from 'react'
import type { MouseEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useParams } from 'react-router-dom'

import { api } from '../features/api'
import { useConversation } from '../hooks/useConversation'
import {
  DRAFT_SETUPS,
  agentIcon,
  badge,
  draftCardMarkup,
  formatTime,
  ghostButton,
  heroCard,
  message,
  miniChip,
  moduleItem,
  panelActivity,
  projectCardMarkup,
  projectDecoration,
  renderPrototypeMessage,
  statusTone,
  summaryStat,
  surfaceRow,
  topLevelViewMeta,
  type UIMessage,
  type Translator,
} from './prototypeShared'
import type {
  ApprovalDetail,
  ApprovalSummary,
  KnowledgeObject,
  ModelPreset,
  ProviderName,
  ReleaseReadiness,
  RunDetail,
  RunSummary,
  SettingsConnectionResult,
  StudioSettingsConnectionTestRequest,
  SpaceType,
} from '../features/types'

type ViewId =
  | 'welcome'
  | 'build'
  | 'dashboard'
  | 'documentation'
  | 'projectOverview'
  | 'projectCreate'
  | 'versionSpace'
  | 'versionCreate'
  | 'personalWorkspace'
  | 'knowledgeGallery'
  | 'knowledgeDetail'
  | 'runs'
  | 'runDetail'
  | 'governance'
  | 'approvalDetail'
  | 'releaseReadiness'

type TabId = string
type LanguageCode = 'en' | 'zh'
type ThemeMode = 'dark' | 'light' | 'system'
type SettingsPanelId = 'model' | 'theme' | 'language' | 'notifications' | null
type NotificationMode = 'important' | 'all' | 'muted'
type CustomProviderKind = 'openai_compatible' | 'openai' | 'gemini' | 'anthropic'
type CustomModelDraft = {
  modelPreset: ModelPreset
  customProviderKind: CustomProviderKind
  customBaseUrl: string
  customModelName: string
}

interface RouteContext {
  projectId: string
  versionId: string
  usId: string
  runId: string
  approvalId: string
  objectId: string
}

function readCustomModelDraft(): CustomModelDraft | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem('nasus.customModelDraft')
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<CustomModelDraft>
    const modelPreset = parsed.modelPreset === 'custom' || parsed.modelPreset === 'system_default'
      ? parsed.modelPreset
      : 'system_default'
    const customProviderKind = parsed.customProviderKind === 'openai' || parsed.customProviderKind === 'gemini' || parsed.customProviderKind === 'anthropic' || parsed.customProviderKind === 'openai_compatible'
      ? parsed.customProviderKind
      : 'openai_compatible'
    return {
      modelPreset,
      customProviderKind,
      customBaseUrl: typeof parsed.customBaseUrl === 'string' ? parsed.customBaseUrl : '',
      customModelName: typeof parsed.customModelName === 'string' ? parsed.customModelName : '',
    }
  } catch {
    return null
  }
}

const WORKSPACE_VIEWS = new Set<ViewId>([
  'projectOverview',
  'versionSpace',
  'versionCreate',
  'personalWorkspace',
  'knowledgeGallery',
  'knowledgeDetail',
  'runs',
  'runDetail',
  'governance',
  'approvalDetail',
  'releaseReadiness',
])

const PANEL_TABS: Record<ViewId, { id: TabId; label: string }[]> = {
  welcome: [
    { id: 'activity', label: 'Activity' },
    { id: 'tips', label: 'Tips' },
    { id: 'status', label: 'Status' },
  ],
  build: [
    { id: 'projects', label: 'Projects' },
    { id: 'imports', label: 'Imports' },
    { id: 'health', label: 'Health' },
  ],
  dashboard: [
    { id: 'alerts', label: 'Alerts' },
    { id: 'progress', label: 'Progress' },
    { id: 'activity', label: 'Activity' },
  ],
  documentation: [
    { id: 'topics', label: 'Topics' },
    { id: 'templates', label: 'Templates' },
    { id: 'updates', label: 'Updates' },
  ],
  projectOverview: [
    { id: 'context', label: 'Context' },
    { id: 'versions', label: 'Versions' },
    { id: 'activity', label: 'Activity' },
  ],
  projectCreate: [
    { id: 'context', label: 'Context' },
    { id: 'assets', label: 'Assets' },
    { id: 'activity', label: 'Activity' },
  ],
  versionSpace: [
    { id: 'board', label: 'Board' },
    { id: 'context', label: 'Context' },
    { id: 'activity', label: 'Activity' },
  ],
  versionCreate: [
    { id: 'summary', label: 'Summary' },
    { id: 'owners', label: 'Owners' },
    { id: 'activity', label: 'Activity' },
  ],
  personalWorkspace: [
    { id: 'assets', label: 'Assets' },
    { id: 'context', label: 'Context' },
    { id: 'activity', label: 'Activity' },
  ],
  knowledgeGallery: [
    { id: 'graph', label: 'Graph' },
    { id: 'branches', label: 'Branches' },
    { id: 'activity', label: 'Activity' },
  ],
  knowledgeDetail: [
    { id: 'context', label: 'Context' },
    { id: 'evidence', label: 'Evidence' },
    { id: 'history', label: 'History' },
  ],
  runs: [
    { id: 'active', label: 'Active' },
    { id: 'channels', label: 'Channels' },
    { id: 'activity', label: 'Activity' },
  ],
  runDetail: [
    { id: 'evidence', label: 'Evidence' },
    { id: 'trace', label: 'Trace' },
    { id: 'activity', label: 'Activity' },
  ],
  governance: [
    { id: 'pending', label: 'Pending' },
    { id: 'policy', label: 'Policy' },
    { id: 'activity', label: 'Activity' },
  ],
  approvalDetail: [
    { id: 'diff', label: 'Diff' },
    { id: 'policy', label: 'Policy' },
    { id: 'activity', label: 'Activity' },
  ],
  releaseReadiness: [
    { id: 'blockers', label: 'Blockers' },
    { id: 'signals', label: 'Signals' },
    { id: 'activity', label: 'Activity' },
  ],
}

const DEFAULT_PANEL_TABS: Record<ViewId, TabId> = {
  welcome: 'activity',
  build: 'projects',
  dashboard: 'alerts',
  documentation: 'topics',
  projectOverview: 'context',
  projectCreate: 'context',
  versionSpace: 'board',
  versionCreate: 'summary',
  personalWorkspace: 'assets',
  knowledgeGallery: 'graph',
  knowledgeDetail: 'context',
  runs: 'active',
  runDetail: 'evidence',
  governance: 'pending',
  approvalDetail: 'diff',
  releaseReadiness: 'blockers',
}

const VERSION_NOTES: Record<string, { releaseWindow: string; pendingMerge: number; risk: string; status: string }> = {
  ver_payment_q2: {
    releaseWindow: 'Apr 15',
    pendingMerge: 1,
    risk: 'High',
    status: 'Execution Phase',
  },
}

const US_NOTES: Record<string, { summary: string; impact: string; branch: string; blockers: number; revision: number }> = {
  us_123: {
    summary: 'Checkout flow update touching payment gateway fallback, saved-card recovery, and receipt handoff.',
    impact: 'Checkout Module, Payment Gateway App, Order Summary',
    branch: 'feature/payment-flow-update',
    blockers: 1,
    revision: 3,
  },
  us_124: {
    summary: 'Refund status orchestration with richer state transitions and retry notifications.',
    impact: 'Refund Service, Status Timeline, Admin Queue',
    branch: 'feature/refund-status-timeline',
    blockers: 0,
    revision: 2,
  },
}

const KNOWLEDGE_OBJECTS: KnowledgeObject[] = [
  {
    id: 'OBJ-CHECKOUT',
    name: 'Checkout Flow',
    type: 'Feature',
    branch: 'Version Shared',
    confidence: '0.91',
    relations: ['Payment Gateway App', 'Order Summary', 'Promo Engine'],
    evidence: ['PR #882', 'Scenario Pack r3', 'Run-9021'],
    freshness: '12 mins ago',
  },
  {
    id: 'OBJ-AUTH',
    name: 'Auth Service',
    type: 'System',
    branch: 'Official',
    confidence: '0.97',
    relations: ['OAuth Callback', 'Session Store', 'Profile API'],
    evidence: ['System Image', 'Legacy Regression Pack'],
    freshness: '1 hr ago',
  },
  {
    id: 'OBJ-ASSET',
    name: 'Checkout Scenario Pack',
    type: 'QualityAssetPack',
    branch: 'Candidate',
    confidence: '0.88',
    relations: ['US-123', 'Run-9021', 'Release Gate'],
    evidence: ['Scenario Set', 'Automation Draft'],
    freshness: '5 mins ago',
  },
]

const DOCS = [
  {
    id: 'DOC-START',
    title: 'Getting Started',
    copy: 'How to create a project, connect sources, and initialize the Official System Image.',
    category: 'Guide',
  },
  {
    id: 'DOC-BRANCHING',
    title: 'System Image & Branching',
    copy: 'Official baseline, version branch overlays, candidate promotion, and baseline write-back.',
    category: 'Concept',
  },
  {
    id: 'DOC-ASSET',
    title: 'Quality Asset Pack',
    copy: 'How scenarios, scope, plans, cases, automation, performance, and change docs work together.',
    category: 'Reference',
  },
]

const RELEASE_DEFAULT = {
  score: 71,
  status: 'Conditionally Ready',
  blockers: 3,
  approvalsOpen: 2,
  pendingMerge: 1,
  executionHealth: '1 failed run pending review',
}

function docCard(doc: { id: string; title: string; copy: string; category: string }) {
  return `
    <div class="collection-card">
      <div class="collection-card-title">${doc.title}</div>
      <div class="collection-card-copy">${doc.copy}</div>
      <div class="collection-card-meta">${miniChip(doc.category, 'info')}</div>
      <div class="collection-card-footer">
        <span class="collection-card-subtitle">Agent-readable guide</span>
        <div style="display:flex;width:100%;justify-content:flex-end;">
          <button class="pill-chip" data-action="search_docs" data-doc="${doc.id}"><i class="fa-solid fa-book-open"></i>Open</button>
        </div>
      </div>
    </div>
  `
}

function viewIdFromPath(pathname: string): ViewId {
  if (pathname === '/welcome' || pathname === '/') return 'welcome'
  if (pathname === '/build') return 'build'
  if (pathname === '/build/create-project') return 'projectCreate'
  if (pathname === '/dashboard') return 'dashboard'
  if (pathname === '/documentation') return 'documentation'
  if (pathname.includes('/release-readiness')) return 'releaseReadiness'
  if (pathname.includes('/governance/') && pathname !== pathname.replace(/\/governance\/[^/]+$/, '')) return 'approvalDetail'
  if (pathname.includes('/governance')) return 'governance'
  if (pathname.includes('/runs/') && pathname !== pathname.replace(/\/runs\/[^/]+$/, '')) return 'runDetail'
  if (pathname.includes('/runs')) return 'runs'
  if (pathname.includes('/knowledge/') && pathname !== pathname.replace(/\/knowledge\/[^/]+$/, '')) return 'knowledgeDetail'
  if (pathname.includes('/knowledge')) return 'knowledgeGallery'
  if (pathname.includes('/workspaces/')) return 'personalWorkspace'
  if (pathname.includes('/versions/create')) return 'versionCreate'
  if (pathname.includes('/versions')) return 'versionSpace'
  if (pathname.startsWith('/projects/')) return 'projectOverview'
  return 'welcome'
}

function routeForView(viewId: ViewId, ctx: RouteContext) {
  switch (viewId) {
    case 'welcome':
      return '/welcome'
    case 'build':
      return '/build'
    case 'projectCreate':
      return '/build/create-project'
    case 'dashboard':
      return '/dashboard'
    case 'documentation':
      return '/documentation'
    case 'projectOverview':
      return `/projects/${ctx.projectId}`
    case 'versionSpace':
      return `/projects/${ctx.projectId}/versions`
    case 'versionCreate':
      return `/projects/${ctx.projectId}/versions/create`
    case 'personalWorkspace':
      return `/projects/${ctx.projectId}/workspaces/${ctx.usId}`
    case 'knowledgeGallery':
      return `/projects/${ctx.projectId}/knowledge`
    case 'knowledgeDetail':
      return `/projects/${ctx.projectId}/knowledge/${ctx.objectId}`
    case 'runs':
      return `/projects/${ctx.projectId}/runs`
    case 'runDetail':
      return `/projects/${ctx.projectId}/runs/${ctx.runId}`
    case 'governance':
      return `/projects/${ctx.projectId}/governance`
    case 'approvalDetail':
      return `/projects/${ctx.projectId}/governance/${ctx.approvalId}`
    case 'releaseReadiness':
      return `/projects/${ctx.projectId}/release-readiness`
  }
}

function conversationScopeForView(viewId: ViewId, ctx: RouteContext): { spaceType: SpaceType; spaceId: string; title: string } {
  switch (viewId) {
    case 'welcome':
      return { spaceType: 'welcome', spaceId: 'welcome', title: 'Welcome' }
    case 'build':
    case 'projectCreate':
      return { spaceType: 'build', spaceId: 'build', title: 'Build' }
    case 'dashboard':
      return { spaceType: 'dashboard', spaceId: 'dashboard', title: 'Dashboard' }
    case 'documentation':
      return { spaceType: 'documentation', spaceId: 'documentation', title: 'Documentation' }
    case 'projectOverview':
      return { spaceType: 'project', spaceId: ctx.projectId, title: 'Project Overview' }
    case 'versionSpace':
    case 'versionCreate':
      return { spaceType: 'version', spaceId: ctx.versionId, title: 'Version Space' }
    case 'personalWorkspace':
      return { spaceType: 'workspace', spaceId: ctx.usId, title: `${ctx.usId} Workspace` }
    case 'knowledgeGallery':
    case 'knowledgeDetail':
      return { spaceType: 'knowledge', spaceId: ctx.projectId, title: 'Knowledge' }
    case 'runs':
    case 'runDetail':
      return { spaceType: 'runs', spaceId: ctx.projectId, title: 'Runs' }
    case 'governance':
    case 'approvalDetail':
    case 'releaseReadiness':
      return { spaceType: 'governance', spaceId: ctx.projectId, title: 'Governance' }
  }
}

export function PrototypeStudio() {
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams()
  const queryClient = useQueryClient()

  const routeContext = useMemo<RouteContext>(() => ({
    projectId: params.projectId ?? 'proj_payment',
    versionId: params.versionId ?? 'ver_payment_q2',
    usId: params.usId ?? 'us_123',
    runId: params.runId ?? 'run_9021',
    approvalId: params.approvalId ?? 'approval_442',
    objectId: params.objectId ?? 'OBJ-CHECKOUT',
  }), [params.approvalId, params.objectId, params.projectId, params.runId, params.usId, params.versionId])

  const viewId = viewIdFromPath(location.pathname)
  const conversationScope = useMemo(() => conversationScopeForView(viewId, routeContext), [routeContext, viewId])
  const {
    conversation,
    conversationId,
    sendMessage,
    isSending,
  } = useConversation(conversationScope.spaceType, conversationScope.spaceId, conversationScope.title)

  const welcomeQuery = useQuery({ queryKey: ['welcome'], queryFn: api.getWelcome })
  const buildQuery = useQuery({ queryKey: ['build'], queryFn: api.getBuild })
  const dashboardQuery = useQuery({ queryKey: ['dashboard'], queryFn: api.getDashboard })
  const documentationQuery = useQuery({ queryKey: ['documentation'], queryFn: api.getDocumentation })
  const settingsQuery = useQuery({ queryKey: ['studio-settings'], queryFn: api.getSettings })
  const projectQuery = useQuery({
    queryKey: ['project', routeContext.projectId],
    queryFn: () => api.getProject(routeContext.projectId),
    enabled: WORKSPACE_VIEWS.has(viewId),
  })
  const workspaceQuery = useQuery({
    queryKey: ['workspace', routeContext.projectId, routeContext.usId],
    queryFn: () => api.getWorkspace(routeContext.projectId, routeContext.usId),
    enabled: viewId === 'personalWorkspace',
  })
  const knowledgeQuery = useQuery({
    queryKey: ['knowledge', routeContext.projectId],
    queryFn: () => api.getKnowledge(routeContext.projectId),
    enabled: viewId === 'knowledgeGallery' || viewId === 'knowledgeDetail',
  })
  const knowledgeDetailQuery = useQuery({
    queryKey: ['knowledge-detail', routeContext.projectId, routeContext.objectId],
    queryFn: () => api.getKnowledgeDetail(routeContext.projectId, routeContext.objectId),
    enabled: viewId === 'knowledgeDetail',
  })
  const runDetailQuery = useQuery({
    queryKey: ['run-detail', routeContext.projectId, routeContext.runId],
    queryFn: () => api.getRunDetail(routeContext.projectId, routeContext.runId),
    enabled: viewId === 'runDetail',
  })
  const approvalDetailQuery = useQuery({
    queryKey: ['approval-detail', routeContext.projectId, routeContext.approvalId],
    queryFn: () => api.getApprovalDetail(routeContext.projectId, routeContext.approvalId),
    enabled: viewId === 'approvalDetail',
  })
  const releaseReadinessQuery = useQuery({
    queryKey: ['release-readiness', routeContext.projectId],
    queryFn: () => api.getReleaseReadiness(routeContext.projectId),
    enabled: viewId === 'releaseReadiness',
  })

  const invokeToolMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.invokeTool>[0]) => api.invokeTool(payload),
    onSuccess: (_, payload) => {
      queryClient.invalidateQueries({ queryKey: ['build'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['welcome'] })
      if (typeof payload.input?.project_id === 'string') {
        queryClient.invalidateQueries({ queryKey: ['project', payload.input.project_id] })
      }
      if (typeof payload.input?.project_id === 'string' && typeof payload.input?.us_id === 'string') {
        queryClient.invalidateQueries({ queryKey: ['workspace', payload.input.project_id, payload.input.us_id] })
      }
    },
  })
  const interruptGoalMutation = useMutation({
    mutationFn: (goalId: string) => api.interruptAgentGoal(goalId),
    onSuccess: (_, goalId) => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
      queryClient.invalidateQueries({ queryKey: ['agent-goal', goalId] })
    },
  })
  const resumeGoalMutation = useMutation({
    mutationFn: (goalId: string) => api.resumeAgentGoal(goalId),
    onSuccess: (_, goalId) => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
      queryClient.invalidateQueries({ queryKey: ['agent-goal', goalId] })
    },
  })
  const feedbackGoalMutation = useMutation({
    mutationFn: ({ goalId, feedback }: { goalId: string; feedback: string }) =>
      api.feedbackAgentGoal(goalId, feedback),
    onSuccess: (_, payload) => {
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
      queryClient.invalidateQueries({ queryKey: ['agent-goal', payload.goalId] })
    },
  })
  const updateSettingsMutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['studio-settings'] })
    },
  })

  const projects = useMemo(() => {
    const source = dashboardQuery.data?.projects
      ?? welcomeQuery.data?.recent_projects
      ?? buildQuery.data?.drafts
      ?? []
    return source
  }, [buildQuery.data?.drafts, dashboardQuery.data?.projects, welcomeQuery.data?.recent_projects])

  const currentProject = useMemo(() => {
    return projectQuery.data?.project
      ?? projects.find((project) => project.id === routeContext.projectId)
      ?? projects[0]
  }, [projectQuery.data?.project, projects, routeContext.projectId])

  const versions = projectQuery.data?.versions ?? []
  const currentVersion = versions.find((version) => version.id === routeContext.versionId) ?? versions[0]
  const usItems = projectQuery.data?.us_items ?? []
  const currentUs = workspaceQuery.data?.us_item ?? usItems.find((item) => item.id === routeContext.usId) ?? usItems[0]
  const runs = workspaceQuery.data?.runs ?? projectQuery.data?.runs ?? []
  const approvals = workspaceQuery.data?.approvals ?? projectQuery.data?.approvals ?? []
  const currentRun = runs.find((item) => item.id === routeContext.runId) ?? runs[0]
  const currentApproval = approvals.find((item) => item.id === routeContext.approvalId) ?? approvals[0]
  const knowledgeObjects = knowledgeQuery.data ?? KNOWLEDGE_OBJECTS
  const currentObject = knowledgeDetailQuery.data ?? knowledgeObjects.find((item) => item.id === routeContext.objectId) ?? KNOWLEDGE_OBJECTS[0]
  const docs = documentationQuery.data ?? DOCS

  const [panelTabs, setPanelTabs] = useState(DEFAULT_PANEL_TABS)
  const [isWaitingForAgent, setIsWaitingForAgent] = useState(false)
  const [composerValue, setComposerValue] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsPanel, setSettingsPanel] = useState<SettingsPanelId>(null)
  const [settingsHydrated, setSettingsHydrated] = useState(false)
  const [language, setLanguage] = useState<LanguageCode>(() => {
    if (typeof window === 'undefined') return 'en'
    return window.localStorage.getItem('nasus.language') === 'zh' ? 'zh' : 'en'
  })
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') return 'dark'
    const storedTheme = window.localStorage.getItem('nasus.theme')
    return storedTheme === 'light' || storedTheme === 'system' ? storedTheme : 'dark'
  })
  const [systemTheme, setSystemTheme] = useState<'dark' | 'light'>(() => {
    if (typeof window === 'undefined') return 'dark'
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  })
  const [modelPreset, setModelPreset] = useState<ModelPreset>(() => {
    if (typeof window === 'undefined') return 'system_default'
    const customDraft = readCustomModelDraft()
    if (customDraft) return customDraft.modelPreset
    const storedPreset = window.localStorage.getItem('nasus.modelPreset')
    return storedPreset === 'system_default' || storedPreset === 'custom'
      ? storedPreset
      : 'system_default'
  })
  const [notificationMode, setNotificationMode] = useState<NotificationMode>(() => {
    if (typeof window === 'undefined') return 'important'
    const storedMode = window.localStorage.getItem('nasus.notificationMode')
    return storedMode === 'all' || storedMode === 'muted' ? storedMode : 'important'
  })
  const [customProviderKind, setCustomProviderKind] = useState<CustomProviderKind>(() => readCustomModelDraft()?.customProviderKind ?? 'openai_compatible')
  const [customBaseUrl, setCustomBaseUrl] = useState(() => readCustomModelDraft()?.customBaseUrl ?? '')
  const [customModelName, setCustomModelName] = useState(() => readCustomModelDraft()?.customModelName ?? '')
  const [customApiKey, setCustomApiKey] = useState('')
  const [customHasApiKey, setCustomHasApiKey] = useState(false)
  const [customMaskedKey, setCustomMaskedKey] = useState<string | null>(null)
  const [releaseState, setReleaseState] = useState(RELEASE_DEFAULT)
  const [assetState, setAssetState] = useState({
    status: 'Drafting',
    scenariosDone: 5,
    scenarioTotal: 5,
    casesDone: 14,
    casesTotal: 18,
    automationStatus: 'Draft Ready',
    performanceStatus: 'Waiting Approval',
    changeDocStatus: 'Ready',
    revision: 'r3',
    pendingExecution: 1,
  })
  const [approvalsState, setApprovalsState] = useState<Record<string, ApprovalSummary>>({})
  const [runsState, setRunsState] = useState<Record<string, RunSummary>>({})
  const [conversationOverrides, setConversationOverrides] = useState<Record<string, UIMessage[]>>({})
  const [connectionTestResult, setConnectionTestResult] = useState<SettingsConnectionResult | null>(null)

  useEffect(() => {
    if (approvals.length) {
      setApprovalsState(Object.fromEntries(approvals.map((approval) => [approval.id, approval])))
    }
  }, [approvals])

  useEffect(() => {
    if (runs.length) {
      setRunsState(Object.fromEntries(runs.map((run) => [run.id, run])))
    }
  }, [runs])

  const currentApprovalResolved = approvalsState[routeContext.approvalId] ?? currentApproval
  const currentRunResolved = runsState[routeContext.runId] ?? currentRun
  const currentRunDetail: RunDetail | undefined = runDetailQuery.data
  const currentApprovalDetail: ApprovalDetail | undefined = approvalDetailQuery.data
  const currentReleaseReadiness: ReleaseReadiness | undefined = releaseReadinessQuery.data

  const tr: Translator = (en: string, zh: string) => (language === 'zh' ? zh : en)
  const resolvedTheme = theme === 'system' ? systemTheme : theme

  useEffect(() => {
    if (!settingsQuery.data || settingsHydrated) return
    const customDraft = readCustomModelDraft()

    setLanguage(settingsQuery.data.language)
    setTheme(settingsQuery.data.theme)
    setModelPreset(customDraft?.modelPreset ?? settingsQuery.data.model_preset)
    setNotificationMode(settingsQuery.data.notification_mode)
    setCustomProviderKind(customDraft?.customProviderKind ?? settingsQuery.data.custom_model.provider_kind)
    setCustomBaseUrl(customDraft?.customBaseUrl ?? settingsQuery.data.custom_model.base_url ?? '')
    setCustomModelName(customDraft?.customModelName ?? settingsQuery.data.custom_model.model_name)
    setCustomHasApiKey(settingsQuery.data.custom_model.has_api_key)
    setCustomMaskedKey(settingsQuery.data.custom_model.api_key_masked ?? null)
    setCustomApiKey('')
    setSettingsHydrated(true)
  }, [settingsHydrated, settingsQuery.data])

  useEffect(() => {
    if (typeof window === 'undefined') return undefined

    const mediaQuery = window.matchMedia('(prefers-color-scheme: light)')
    const syncSystemTheme = () => setSystemTheme(mediaQuery.matches ? 'light' : 'dark')
    syncSystemTheme()

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', syncSystemTheme)
      return () => mediaQuery.removeEventListener('change', syncSystemTheme)
    }

    mediaQuery.addListener(syncSystemTheme)
    return () => mediaQuery.removeListener(syncSystemTheme)
  }, [])

  useEffect(() => {
    if (!settingsOpen) {
      setSettingsPanel(null)
    }
  }, [settingsOpen])

  useEffect(() => {
    if (settingsOpen || !settingsQuery.data) return
    const customDraft = readCustomModelDraft()

    setModelPreset(customDraft?.modelPreset ?? settingsQuery.data.model_preset)
    setCustomProviderKind(customDraft?.customProviderKind ?? settingsQuery.data.custom_model.provider_kind)
    setCustomBaseUrl(customDraft?.customBaseUrl ?? settingsQuery.data.custom_model.base_url ?? '')
    setCustomModelName(customDraft?.customModelName ?? settingsQuery.data.custom_model.model_name)
    setCustomHasApiKey(settingsQuery.data.custom_model.has_api_key)
    setCustomMaskedKey(settingsQuery.data.custom_model.api_key_masked ?? null)
    setCustomApiKey('')
  }, [settingsOpen, settingsQuery.data])

  useEffect(() => {
    if (!settingsOpen) {
      setConnectionTestResult(null)
    }
  }, [settingsOpen])

  useEffect(() => {
    if (settingsPanel === 'model') {
      setConnectionTestResult(null)
    }
  }, [customApiKey, customBaseUrl, customModelName, customProviderKind, modelPreset, settingsPanel])

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'
    window.localStorage.setItem('nasus.theme', theme)
    window.localStorage.setItem('nasus.language', language)
    window.localStorage.setItem('nasus.modelPreset', modelPreset)
    window.localStorage.setItem('nasus.notificationMode', notificationMode)
  }, [language, modelPreset, notificationMode, resolvedTheme, theme])

  useEffect(() => {
    if (typeof window === 'undefined') return

    window.localStorage.setItem(
      'nasus.customModelDraft',
      JSON.stringify({
        modelPreset,
        customProviderKind,
        customBaseUrl,
        customModelName,
      } satisfies CustomModelDraft),
    )
  }, [customBaseUrl, customModelName, customProviderKind, modelPreset])

  useEffect(() => {
    if (!settingsHydrated) return

    updateSettingsMutation.mutate({
      language,
      theme,
      notification_mode: notificationMode,
    })
  }, [language, notificationMode, settingsHydrated, theme])

  const modelOptions: { value: ModelPreset; label: string; detail: string; icon: string }[] = [
    {
      value: 'system_default',
      label: tr('Default system model', '默认系统模型'),
      detail: tr('Use the system-managed provider route and fallback policy.', '使用系统维护的 Provider 路由与回退策略。'),
      icon: 'fa-solid fa-circle-nodes',
    },
    {
      value: 'custom',
      label: tr('Custom model', '自定义模型'),
      detail: tr('Configure a custom provider, base URL, model, and API key.', '配置自定义 Provider、Base URL、Model 和 API Key。'),
      icon: 'fa-solid fa-sliders',
    },
  ]

  const currentModelOption = modelOptions.find((option) => option.value === modelPreset) ?? modelOptions[0]
  const activeProviderStatus = settingsQuery.data?.active_provider_status
  const persistedProvider = settingsQuery.data?.model_provider ?? 'openai'
  const activeProvider = connectionTestResult?.provider
    ?? (modelPreset === 'custom'
      ? customProviderKind
      : persistedProvider)

  function providerLabel(provider: ProviderName) {
    switch (provider) {
      case 'openai':
        return 'OpenAI'
      case 'gemini':
        return 'Gemini'
      case 'anthropic':
        return 'Anthropic'
      case 'openai_compatible':
        return tr('OpenAI-compatible', 'OpenAI 兼容')
      default:
        return tr('Fallback', '回退')
    }
  }

  const runtimeModeLabel = settingsQuery.data?.runtime_mode === 'live'
    ? tr('live', 'live')
    : tr('fallback', 'fallback')
  const currentModelDetail = settingsQuery.data
    ? `${providerLabel(persistedProvider)} · ${settingsQuery.data.model_name} · ${runtimeModeLabel}`
    : currentModelOption.label
  const providerBannerMode = connectionTestResult?.runtime_mode ?? settingsQuery.data?.runtime_mode ?? activeProviderStatus?.mode ?? 'fallback'
  const providerBannerAvailability = connectionTestResult?.ok ?? activeProviderStatus?.available ?? false
  const providerBannerMessage = connectionTestResult?.message
    ?? activeProviderStatus?.reason
    ?? tr('No provider status returned yet.', '当前尚未返回 Provider 状态。')
  const providerBannerFallback = connectionTestResult?.fallback_provider
    ?? activeProviderStatus?.fallback_provider
    ?? settingsQuery.data?.fallback_provider
    ?? null

  const testConnectionMutation = useMutation({
    mutationFn: (payload: StudioSettingsConnectionTestRequest) => api.testSettingsConnection(payload),
    onSuccess: (result) => {
      setConnectionTestResult(result)
      queryClient.invalidateQueries({ queryKey: ['studio-settings'] })
    },
    onError: (error) => {
      setConnectionTestResult({
        ok: false,
        provider: activeProvider,
        model_name: modelPreset === 'custom' ? customModelName.trim() || 'custom-model' : settingsQuery.data?.model_name ?? 'system_default',
        runtime_mode: 'fallback',
        message: error instanceof Error ? error.message : 'Connection test failed.',
      })
    },
  })

  function handleSettingsAction(action: 'status' | 'terms' | 'privacy' | 'feedback' | 'billing') {
    setSettingsOpen(false)
    setSettingsPanel(null)

    if (action === 'status') {
      navigateToView('dashboard')
      return
    }

    if (action === 'feedback') {
      setComposerValue(tr('I want to share product feedback about the current workspace.', '我想反馈一下当前工作台的体验问题。'))
      return
    }

    navigateToView('documentation')
  }

  function buildCustomModelPayload() {
    const payload: StudioSettingsConnectionTestRequest = {
      custom_provider_kind: customProviderKind,
      custom_base_url: customBaseUrl,
      custom_model_name: customModelName,
      model_preset: 'custom',
    }

    if (customApiKey.trim()) {
      payload.custom_api_key = customApiKey.trim()
    }

    return payload
  }

  function buildConnectionTestPayload(): StudioSettingsConnectionTestRequest {
    if (modelPreset === 'custom') {
      return buildCustomModelPayload()
    }

    return { model_preset: 'system_default' }
  }

  async function saveSystemModelConfig() {
    const updated = await updateSettingsMutation.mutateAsync({
      model_preset: 'system_default',
    })
    setModelPreset(updated.model_preset)
    window.localStorage.setItem(
      'nasus.customModelDraft',
      JSON.stringify({
        modelPreset: updated.model_preset,
        customProviderKind,
        customBaseUrl,
        customModelName,
      } satisfies CustomModelDraft),
    )
    setConnectionTestResult(null)
  }

  async function saveCustomModelConfig() {
    const updated = await updateSettingsMutation.mutateAsync(buildCustomModelPayload() as unknown as Record<string, unknown>)
    setModelPreset(updated.model_preset)
    setCustomProviderKind(updated.custom_model.provider_kind)
    setCustomBaseUrl(updated.custom_model.base_url ?? '')
    setCustomModelName(updated.custom_model.model_name)
    setCustomHasApiKey(updated.custom_model.has_api_key)
    setCustomMaskedKey(updated.custom_model.api_key_masked ?? null)
    setCustomApiKey('')
    window.localStorage.setItem(
      'nasus.customModelDraft',
      JSON.stringify({
        modelPreset: updated.model_preset,
        customProviderKind: updated.custom_model.provider_kind,
        customBaseUrl: updated.custom_model.base_url ?? '',
        customModelName: updated.custom_model.model_name,
      } satisfies CustomModelDraft),
    )
    setConnectionTestResult(null)
  }

  async function testModelConnection() {
    await testConnectionMutation.mutateAsync(buildConnectionTestPayload())
  }

  function renderSettingsSubmenu() {
    if (settingsPanel === 'theme') {
      const themeOptions: { value: ThemeMode; label: string; icon: string }[] = [
        { value: 'light', label: tr('Light', '浅色'), icon: 'fa-regular fa-sun' },
        { value: 'dark', label: tr('Dark', '深色'), icon: 'fa-regular fa-moon' },
        { value: 'system', label: tr('System', '跟随系统'), icon: 'fa-solid fa-circle-half-stroke' },
      ]

      return (
        <div className="settings-submenu settings-subpanel-card">
          <div className="settings-subpanel-header">
            <button className="settings-subpanel-back" type="button" onClick={() => setSettingsPanel(null)}>
              <i className="fa-solid fa-chevron-left" />
              <span>{tr('Back', '返回')}</span>
            </button>
          </div>
          <div className="settings-submenu-title">{tr('Theme', '主题')}</div>
          <div className="settings-submenu-list">
            {themeOptions.map((option) => (
              <button
                className={`settings-submenu-option ${theme === option.value ? 'active' : ''}`}
                key={option.value}
                type="button"
                onClick={() => setTheme(option.value)}
              >
                <span className="settings-radio">{theme === option.value ? <span /> : null}</span>
                <i className={option.icon} />
                <span>{option.label}</span>
              </button>
            ))}
          </div>
        </div>
      )
    }

    if (settingsPanel === 'language') {
      const languageOptions: { value: LanguageCode; label: string; detail: string }[] = [
        { value: 'en', label: 'English', detail: tr('Workspace copy and navigation in English', '工作台文案与导航使用英文') },
        { value: 'zh', label: '中文', detail: tr('Workspace copy and navigation in Chinese', '工作台文案与导航使用中文') },
      ]

      return (
        <div className="settings-submenu settings-subpanel-card">
          <div className="settings-subpanel-header">
            <button className="settings-subpanel-back" type="button" onClick={() => setSettingsPanel(null)}>
              <i className="fa-solid fa-chevron-left" />
              <span>{tr('Back', '返回')}</span>
            </button>
          </div>
          <div className="settings-submenu-title">{tr('Language', '语言')}</div>
          <div className="settings-submenu-list">
            {languageOptions.map((option) => (
              <button
                className={`settings-submenu-option stacked ${language === option.value ? 'active' : ''}`}
                key={option.value}
                type="button"
                onClick={() => setLanguage(option.value)}
              >
                <span className="settings-radio">{language === option.value ? <span /> : null}</span>
                <span className="settings-option-copy">
                  <span className="settings-option-label">{option.label}</span>
                  <span className="settings-option-detail">{option.detail}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )
    }

    if (settingsPanel === 'model') {
      const connectionResultTone = connectionTestResult
        ? !connectionTestResult.ok
          ? 'error'
          : connectionTestResult.runtime_mode === 'live'
            ? 'success'
            : 'warning'
        : null

      return (
        <div className="settings-submenu wide settings-subpanel-card">
          <div className="settings-subpanel-header">
            <button className="settings-subpanel-back" type="button" onClick={() => setSettingsPanel(null)}>
              <i className="fa-solid fa-chevron-left" />
              <span>{tr('Back', '返回')}</span>
            </button>
          </div>
          <div className="settings-submenu-title">{tr('Model configuration', '模型配置')}</div>
          <div className="settings-submenu-caption">
            {settingsQuery.data
              ? tr(
                  `Main agent route: ${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`,
                  `主 Agent 路由：${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`,
                )
              : tr('Select the workspace default used by the main agent for planning and generation.', '选择主 Agent 在规划与生成时默认使用的工作模型。')}
          </div>
          <div className="settings-provider-banner">
            <div className="settings-provider-status-row">
              <span className="settings-provider-pill neutral">{providerLabel(activeProvider)}</span>
              <span className={`settings-provider-pill ${providerBannerMode === 'live' ? 'live' : 'fallback'}`}>
                {providerBannerMode === 'live' ? tr('live', 'live') : tr('fallback', 'fallback')}
              </span>
              {(connectionTestResult || activeProviderStatus) ? (
                <span className={`settings-provider-pill ${providerBannerAvailability ? 'good' : 'warn'}`}>
                  {providerBannerAvailability ? tr('Provider ready', 'Provider 已就绪') : tr('Provider unavailable', 'Provider 不可用')}
                </span>
              ) : null}
            </div>
            <span className="settings-provider-copy">
              {providerBannerMessage}
            </span>
            {providerBannerFallback ? (
              <span className="settings-runtime-copy">
                {tr(`Fallback provider: ${providerBannerFallback}`, `回退 Provider：${providerBannerFallback}`)}
              </span>
            ) : null}
          </div>
          <div className="settings-submenu-list">
            {modelOptions.map((option) => (
              <button
                className={`settings-submenu-option stacked ${modelPreset === option.value ? 'active' : ''}`}
                key={option.value}
                type="button"
                onClick={() => setModelPreset(option.value)}
              >
                <span className="settings-radio">{modelPreset === option.value ? <span /> : null}</span>
                <i className={option.icon} />
                <span className="settings-option-copy">
                  <span className="settings-option-label">{option.label}</span>
                  <span className="settings-option-detail">{option.detail}</span>
                </span>
              </button>
            ))}
          </div>
          {modelPreset === 'custom' ? (
            <div className="settings-form-block">
              <div className="settings-form-title">{tr('Custom model route', '自定义模型路由')}</div>
              <div className="settings-form-copy">
                {tr(
                  'Use this when you want Nasus to call an OpenAI-compatible endpoint or your own provider route.',
                  '当你希望 Nasus 调用 OpenAI 兼容接口或你自己的 Provider 路由时使用。',
                )}
              </div>
              <label className="settings-field">
                <span className="settings-field-label">{tr('Provider type', 'Provider 类型')}</span>
                <select className="settings-field-control" value={customProviderKind} onChange={(event) => setCustomProviderKind(event.target.value as CustomProviderKind)}>
                  <option value="openai_compatible">{tr('OpenAI-compatible', 'OpenAI 兼容')}</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </label>
              <label className="settings-field">
                <span className="settings-field-label">Base URL</span>
                <input
                  className="settings-field-control"
                  type="text"
                  placeholder={tr('https://api.example.com/v1', 'https://api.example.com/v1')}
                  value={customBaseUrl}
                  onChange={(event) => setCustomBaseUrl(event.target.value)}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field-label">{tr('Model name', '模型名称')}</span>
                <input
                  className="settings-field-control"
                  type="text"
                  placeholder={tr('your-model-name', 'your-model-name')}
                  value={customModelName}
                  onChange={(event) => setCustomModelName(event.target.value)}
                />
              </label>
              <label className="settings-field">
                <span className="settings-field-label">API Key</span>
                <input
                  className="settings-field-control"
                  type="password"
                  placeholder={customHasApiKey && customMaskedKey ? `${tr('Saved', '已保存')} ${customMaskedKey}` : tr('Paste API key', '粘贴 API Key')}
                  value={customApiKey}
                  onChange={(event) => setCustomApiKey(event.target.value)}
                />
              </label>
              <div className="settings-form-meta">
                {customHasApiKey && customMaskedKey
                  ? tr(`Saved key: ${customMaskedKey}`, `已保存密钥：${customMaskedKey}`)
                  : tr('No custom API key saved yet.', '尚未保存自定义 API Key。')}
              </div>
              <div className="settings-form-meta">
                {tr(
                  'Base URL, provider type, and model name are kept as a local draft across refresh. API keys are only persisted after Save custom model.',
                  'Base URL、Provider 类型和模型名会在刷新后保留为本地草稿；API Key 只有点击“保存自定义模型”后才会持久化。',
                )}
              </div>
              <div className="settings-form-actions">
                <button
                  className="settings-save-button secondary"
                  type="button"
                  disabled={testConnectionMutation.isPending}
                  onClick={() => void testModelConnection()}
                >
                  {testConnectionMutation.isPending ? tr('Testing...', '测试中...') : tr('Test connection', '测试连接')}
                </button>
                <button
                  className="settings-save-button"
                  type="button"
                  disabled={updateSettingsMutation.isPending}
                  onClick={() => void saveCustomModelConfig()}
                >
                  {tr('Save custom model', '保存自定义模型')}
                </button>
              </div>
            </div>
          ) : (
            <div className="settings-form-block">
              <div className="settings-form-title">{tr('System-managed route', '系统托管路由')}</div>
              <div className="settings-form-copy">
                {tr(
                  'Nasus will use the backend-managed default provider route. You can test the current route status without opening the custom provider form.',
                  'Nasus 会使用后端托管的默认 Provider 路由。你可以直接测试当前路由状态，无需展开自定义配置。',
                )}
              </div>
              <div className="settings-form-meta">
                {settingsQuery.data
                  ? tr(
                      `Current route: ${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`,
                      `当前路由：${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`,
                    )
                  : tr('Settings are loading from the server.', '正在从服务端加载设置。')}
              </div>
              <div className="settings-form-actions">
                <button
                  className="settings-save-button secondary"
                  type="button"
                  disabled={testConnectionMutation.isPending}
                  onClick={() => void testModelConnection()}
                >
                  {testConnectionMutation.isPending ? tr('Testing...', '测试中...') : tr('Test connection', '测试连接')}
                </button>
                <button
                  className="settings-save-button"
                  type="button"
                  disabled={updateSettingsMutation.isPending}
                  onClick={() => void saveSystemModelConfig()}
                >
                  {tr('Use default system model', '使用默认系统模型')}
                </button>
              </div>
            </div>
          )}
          {connectionTestResult ? (
            <div className={`settings-test-result ${connectionResultTone ?? 'warning'}`}>
              <div className="settings-test-result-header">
                <span className="settings-test-result-title">
                  {!connectionTestResult.ok
                    ? tr('Connection unavailable', '连接不可用')
                    : connectionTestResult.runtime_mode === 'live'
                      ? tr('Connection healthy', '连接成功')
                      : tr('Fallback active', '已进入回退')}
                </span>
              </div>
              <div className="settings-test-result-copy">
                {providerLabel(connectionTestResult.provider)} / {connectionTestResult.model_name} · {connectionTestResult.runtime_mode === 'live' ? tr('live', 'live') : tr('fallback', 'fallback')}
              </div>
              {typeof connectionTestResult.latency_ms === 'number' ? (
                <div className="settings-test-result-time">
                  {tr(`Latency ${connectionTestResult.latency_ms} ms`, `延迟 ${connectionTestResult.latency_ms} ms`)}
                </div>
              ) : null}
              {connectionTestResult.fallback_provider ? (
                <div className="settings-test-result-time">
                  {tr(
                    `Fallback provider ${connectionTestResult.fallback_provider}`,
                    `回退 Provider ${connectionTestResult.fallback_provider}`,
                  )}
                </div>
              ) : null}
              <div className="settings-test-result-copy">{connectionTestResult.message}</div>
            </div>
          ) : null}
        </div>
      )
    }

    if (settingsPanel === 'notifications') {
      const notificationOptions: { value: NotificationMode; label: string; detail: string }[] = [
        {
          value: 'important',
          label: tr('Important only', '仅重要通知'),
          detail: tr('Approvals, conflicts, and failed runs', '审批、冲突和失败执行'),
        },
        {
          value: 'all',
          label: tr('All updates', '全部更新'),
          detail: tr('Include progress, summaries, and activity signals', '包含进度、总结和活动信号'),
        },
        {
          value: 'muted',
          label: tr('Mute', '静默'),
          detail: tr('Keep alerts inside the activity panel only', '仅在活动面板内保留提醒'),
        },
      ]

      return (
        <div className="settings-submenu wide settings-subpanel-card">
          <div className="settings-subpanel-header">
            <button className="settings-subpanel-back" type="button" onClick={() => setSettingsPanel(null)}>
              <i className="fa-solid fa-chevron-left" />
              <span>{tr('Back', '返回')}</span>
            </button>
          </div>
          <div className="settings-submenu-title">{tr('Applet notifications', '工作台通知')}</div>
          <div className="settings-submenu-list">
            {notificationOptions.map((option) => (
              <button
                className={`settings-submenu-option stacked ${notificationMode === option.value ? 'active' : ''}`}
                key={option.value}
                type="button"
                onClick={() => setNotificationMode(option.value)}
              >
                <span className="settings-radio">{notificationMode === option.value ? <span /> : null}</span>
                <span className="settings-option-copy">
                  <span className="settings-option-label">{option.label}</span>
                  <span className="settings-option-detail">{option.detail}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )
    }

    return null
  }

  function conversationKey(view: ViewId) {
    if (view === 'personalWorkspace') return `personalWorkspace:${routeContext.usId}`
    if (view === 'runDetail') return `runDetail:${routeContext.runId}`
    if (view === 'approvalDetail') return `approvalDetail:${routeContext.approvalId}`
    if (view === 'knowledgeDetail') return `knowledgeDetail:${routeContext.objectId}`
    return view
  }

  function goalPhaseLabel(phase?: string | null) {
    switch (phase) {
      case 'thinking':
        return tr('Thinking', '思考中')
      case 'acting':
        return tr('Acting', '执行中')
      case 'observing':
        return tr('Observing', '观察中')
      case 'deciding':
        return tr('Deciding', '决策中')
      default:
        return tr('Step', '步骤')
    }
  }

  function goalStepSubtitle(step: {
    phase?: string | null
    reasoning?: string | null
    selected_tool_id?: string | null
    observation_summary?: string | null
    decision?: string | null
    decision_rationale?: string | null
    next_plan_hint?: string | null
    status: string
  }) {
    const parts = [
      step.reasoning,
      step.selected_tool_id ? tr(`Tool: ${step.selected_tool_id}`, `工具：${step.selected_tool_id}`) : null,
      step.observation_summary,
      step.decision ? tr(`Decision: ${step.decision}`, `决策：${step.decision}`) : null,
      step.decision_rationale,
      step.next_plan_hint ? tr(`Next: ${step.next_plan_hint}`, `下一步：${step.next_plan_hint}`) : null,
    ].filter(Boolean)

    if (!parts.length) {
      return tr(`Step status: ${step.status}`, `步骤状态：${step.status}`)
    }

    return parts.join(' · ')
  }

  const serverConversationMessages = useMemo<UIMessage[]>(() => {
    if (!conversation) return []

    const messageItems = conversation.messages.map((item) => {
      const html = item.blocks
        .map((block) => `<p style="margin:0 0 8px;">${block.text}</p>`)
        .join('')

      return {
        role: item.role === 'user' ? 'user' : 'agent',
        time: new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        name: item.role === 'assistant' ? 'Nasus Agent' : item.role === 'system' ? 'Nasus System' : 'You',
        text: item.role === 'user' ? item.blocks.map((block) => block.text).join('\n') : undefined,
        html: item.role === 'user' ? undefined : `<div class="markdown-content">${html}</div>`,
      } satisfies UIMessage
    })

    const goalItems = conversation.agent_goals.map((goal) => ({
      role: 'agent' as const,
      time: formatTime(),
      name: 'Nasus Agent Loop',
      html: `
        <div class="surface-section" style="margin:0;">
          <div class="surface-section-header">
            <div>
              <h3 class="surface-section-title">${goal.title}</h3>
              <p class="surface-section-subtitle">${goal.summary}</p>
            </div>
          </div>
          <div class="surface-grid">
            ${summaryStat(tr('Status', '状态'), goal.status, tr(`Autonomy: ${goal.autonomy_level}`, `自主级别：${goal.autonomy_level}`))}
            ${summaryStat(tr('Progress', '进度'), `${goal.steps_completed}/${goal.max_steps}`, goal.pause_reason ? tr(`Pause: ${goal.pause_reason}`, `暂停原因：${goal.pause_reason}`) : tr('Loop active', '循环运行中'))}
          </div>
          <div class="surface-row-meta" style="margin:12px 0 0;display:flex;flex-wrap:wrap;gap:8px;">
            ${goal.status === 'running' ? `<button class="pill-chip" data-action="interrupt_goal" data-goal-id="${goal.id}"><i class="fa-solid fa-pause"></i>${tr('Pause loop', '暂停循环')}</button>` : ''}
            ${goal.status === 'paused' ? `<button class="pill-chip primary" data-action="resume_goal" data-goal-id="${goal.id}"><i class="fa-solid fa-play"></i>${tr('Resume loop', '恢复循环')}</button>` : ''}
            <button class="pill-chip" data-action="goal_feedback" data-goal-id="${goal.id}"><i class="fa-solid fa-message"></i>${tr('Guide next step', '补充下一步意图')}</button>
          </div>
          <div class="surface-list" style="margin-top:12px;">
            ${goal.steps.map((step) => surfaceRow(
              step.title,
              goalStepSubtitle(step),
              [
                miniChip(step.status, statusTone(step.status)),
                step.phase ? miniChip(goalPhaseLabel(step.phase), 'info') : '',
                step.selected_tool_id ? miniChip(step.selected_tool_id, 'good') : '',
                step.next_plan_hint ? miniChip(tr('next', '下一步'), 'warn') : '',
              ].filter(Boolean),
            )).join('')}
          </div>
        </div>
      `,
    }))

    return [...messageItems, ...goalItems]
  }, [conversation, tr])

  const currentConversation = [
    ...seedConversation(viewId),
    ...serverConversationMessages,
    ...(conversationOverrides[conversationKey(viewId)] ?? []),
  ]

  function viewMeta() {
    const versionNote = currentVersion ? VERSION_NOTES[currentVersion.id] : undefined
    return {
      welcome: topLevelViewMeta('welcome', tr),
      build: topLevelViewMeta('build', tr),
      dashboard: topLevelViewMeta('dashboard', tr),
      documentation: {
        title: tr('Documentation', '产品文档'),
        badge: badge(tr('Guides', '指南'), 'review'),
        panelTitle: tr('Docs Navigator', '文档导航'),
        placeholder: tr('Ask how Nasus works, how to use branching, or how a workflow closes.', '询问 Nasus 的工作方式、分支机制，或某个流程如何闭环。'),
      },
      projectOverview: {
        title: `${currentProject?.name ?? tr('Project', '项目')} · ${tr('Project Overview', '项目概览')}`,
        badge: badge(tr('Workspace', '工作空间'), 'active'),
        panelTitle: tr('Project Context', '项目上下文'),
        placeholder: tr('Ask Nasus to refresh the system image, review imports, or launch a version.', '让 Nasus 刷新系统画像、检查导入结果，或启动一个版本。'),
      },
      projectCreate: {
        title: tr('Create Project', '创建项目'),
        badge: badge(tr('Setup Flow', '配置流程'), 'progress'),
        panelTitle: tr('Project Setup', '项目配置'),
        placeholder: tr('Describe the repositories, docs, boards, and quality assets to import.', '描述要导入的仓库、文档、设计板和质量资产。'),
      },
      versionSpace: {
        title: `${currentVersion?.name ?? tr('Version', '版本')} · ${tr('Version Space', '版本空间')}`,
        badge: badge(tr(versionNote?.status ?? currentVersion?.status ?? 'In Progress', versionNote?.status ?? currentVersion?.status ?? '进行中'), 'progress'),
        panelTitle: tr('Version Pulse', '版本动态'),
        placeholder: tr('Ask for version progress, blockers, risk, or owner-level closure.', '查询版本进度、阻塞项、风险，或负责人维度的闭环情况。'),
      },
      versionCreate: {
        title: tr('Create Version Branch', '创建版本分支'),
        badge: badge(tr('Branching', '分支配置'), 'review'),
        panelTitle: tr('Version Setup', '版本配置'),
        placeholder: tr('Describe the release branch, imported US input, and owner assignment plan.', '描述发布分支、导入的 US 内容，以及负责人分配计划。'),
      },
      personalWorkspace: {
        title: `${currentUs?.id ?? 'US'} ${tr('Quality Workspace', '质量工作台')}`,
        badge: badge(tr(currentUs?.status ?? 'In Progress', currentUs?.status ?? '进行中'), 'progress'),
        panelTitle: tr('Asset Pack', '资产包'),
        placeholder: tr('Generate assets, inspect context, or continue the US quality closure.', '生成资产、查看上下文，或继续推进当前 US 的质量闭环。'),
      },
      knowledgeGallery: {
        title: tr('Knowledge Gallery', '知识图谱'),
        badge: badge(tr('System Image', '系统画像'), 'info'),
        panelTitle: tr('Knowledge Context', '知识上下文'),
        placeholder: tr('Ask about system objects, evidence, branch lineage, or risk hotspots.', '查询系统对象、证据链、分支来源，或风险热点。'),
      },
      knowledgeDetail: {
        title: `${currentObject.name} · ${tr('Object Detail', '对象详情')}`,
        badge: badge(tr(currentObject.branch, currentObject.branch), 'info'),
        panelTitle: tr('Object Detail', '对象详情'),
        placeholder: tr('Ask for object lineage, related US, or evidence-backed impact.', '查询对象来源、关联 US，或基于证据的影响分析。'),
      },
      runs: {
        title: tr('Execution Runs', '执行记录'),
        badge: badge(tr('Canonical Run Model', '标准 Run 模型'), 'info'),
        panelTitle: tr('Run Queue', '执行队列'),
        placeholder: tr('Ask about run health, channels, failures, or execution backlog.', '查询执行健康度、通道、失败详情，或执行积压。'),
      },
      runDetail: {
        title: `${currentRunResolved?.id ?? 'Run'} · ${tr('Run Detail', '执行详情')}`,
        badge: badge(tr(currentRunResolved?.status ?? 'Reviewing', currentRunResolved?.status ?? '审核中'), (currentRunResolved?.status ?? '').toLowerCase().includes('fail') ? 'danger' : 'active'),
        panelTitle: tr('Run Evidence', '执行证据'),
        placeholder: tr('Explain the failure, inspect trace, or propose healing.', '解释失败原因、查看 trace，或生成自愈建议。'),
      },
      governance: {
        title: tr('Governance', '治理审批'),
        badge: badge(tr('Approval Queue', '审批队列'), 'review'),
        panelTitle: tr('Governance Queue', '治理队列'),
        placeholder: tr('Ask what is waiting approval, what is blocked, or what needs merge resolution.', '查询待审批项、阻塞项，或需要合并解决的问题。'),
      },
      approvalDetail: {
        title: currentApprovalResolved?.title ?? tr('Approval Detail', '审批详情'),
        badge: badge(tr(currentApprovalResolved?.status ?? 'Waiting Approval', currentApprovalResolved?.status ?? '待审批'), 'review'),
        panelTitle: tr('Approval Detail', '审批详情'),
        placeholder: tr('Ask why this item is blocked or how the merge should be resolved.', '查询为什么被拦截，或应该如何解决当前合并冲突。'),
      },
      releaseReadiness: {
        title: `${currentVersion?.name ?? tr('Version', '版本')} · ${tr('Release Readiness', '发布准备度')}`,
        badge: badge(tr(releaseState.status, releaseState.status), 'progress'),
        panelTitle: tr('Release Gate', '发布闸口'),
        placeholder: tr('Ask if the version is ready, what still blocks release, or what to close next.', '查询版本是否可发布、还有哪些阻塞，或下一步该关闭什么。'),
      },
    }[viewId]
  }

  function navigateToView(targetView: ViewId, overrides: Partial<RouteContext> = {}) {
    const nextContext = { ...routeContext, ...overrides }
    navigate(routeForView(targetView, nextContext))
  }

  function pushUserMessage(text: string) {
    setConversationOverrides((current) => {
      const key = conversationKey(viewId)
      return {
        ...current,
        [key]: [...(current[key] ?? []), message('user', { time: formatTime(), text })],
      }
    })
  }

  function pushAgentMessage(html: string, name = 'Nasus Agent') {
    setConversationOverrides((current) => {
      const key = conversationKey(viewId)
      return {
        ...current,
        [key]: [...(current[key] ?? []), message('agent', { time: formatTime(), name, html })],
      }
    })
  }

  function extractProjectName(text: string) {
    const quoted = text.match(/["']([^"']+)["']/)
    if (quoted) return quoted[1]
    const named = text.match(/project(?: called| named)? ([A-Za-z0-9 _-]+)/i)
    if (named) return named[1].trim()
    if (text.includes('项目')) return 'New Quality Project'
    return `Project ${projects.length + 1}`
  }

  async function invokeAction(action: string, payload: Partial<RouteContext & { project?: string; doc?: string }> = {}) {
    const nextProjectId = payload.project ?? payload.projectId ?? routeContext.projectId
    const nextUsId = payload.usId ?? routeContext.usId
    const nextRunId = payload.runId ?? routeContext.runId
    const nextApprovalId = payload.approvalId ?? routeContext.approvalId
    const nextObjectId = payload.objectId ?? routeContext.objectId

    switch (action) {
      case 'open_welcome':
        navigateToView('welcome')
        return
      case 'open_build':
        navigateToView('build')
        return
      case 'open_dashboard':
        navigateToView('dashboard')
        return
      case 'open_documentation':
        navigateToView('documentation')
        return
      case 'open_project':
        navigateToView('projectOverview', { projectId: nextProjectId })
        return
      case 'open_project_create':
        navigateToView('projectCreate')
        return
      case 'open_version_space':
        navigateToView('versionSpace', { projectId: nextProjectId })
        return
      case 'open_version_create':
        navigateToView('versionCreate', { projectId: nextProjectId })
        return
      case 'open_us_workspace':
        navigateToView('personalWorkspace', { projectId: nextProjectId, usId: nextUsId })
        return
      case 'open_knowledge_gallery':
        navigateToView('knowledgeGallery', { projectId: nextProjectId })
        return
      case 'open_knowledge_detail':
        navigateToView('knowledgeDetail', { projectId: nextProjectId, objectId: nextObjectId })
        return
      case 'open_runs':
        navigateToView('runs', { projectId: nextProjectId })
        return
      case 'open_run_detail':
        navigateToView('runDetail', { projectId: nextProjectId, runId: nextRunId })
        return
      case 'open_governance':
        navigateToView('governance', { projectId: nextProjectId })
        return
      case 'open_approval_detail':
        navigateToView('approvalDetail', { projectId: nextProjectId, approvalId: nextApprovalId })
        return
      case 'open_release_readiness':
        navigateToView('releaseReadiness', { projectId: nextProjectId })
        return
      case 'generate_scenarios':
        setAssetState((current) => ({
          ...current,
          scenariosDone: 8,
          scenarioTotal: 8,
          casesDone: 12,
          casesTotal: 12,
          automationStatus: 'Playwright draft ready',
        }))
        await invokeToolMutation.mutateAsync({
          conversation_id: conversationId,
          tool_id: 'quality.scenario.generate',
          input: {
            project_id: currentProject?.id ?? routeContext.projectId,
            us_id: currentUs?.id ?? routeContext.usId,
          },
        })
        return
      case 'agent_create_project': {
        pushUserMessage('Help me create a new project.')
        pushAgentMessage(`
          <div class="markdown-content">
            <p>I can guide the setup. To create a project and initialize its system image, please provide:</p>
            <ol style="margin:8px 0 0 18px;padding:0;">
              <li>Git repository URLs</li>
              <li>US / PRD documents</li>
              <li>UX boards or screenshots</li>
              <li>Historical tests or quality assets if available</li>
            </ol>
            <p style="margin-top:8px;">I will convert that into a structured project draft, validate the sources, and then prepare the initialization plan.</p>
          </div>
        `, 'Nasus Setup Agent')
        navigateToView('projectCreate')
        return
      }
      case 'create_version_branch': {
        if (nextProjectId) {
          await invokeToolMutation.mutateAsync({
            conversation_id: conversationId,
            tool_id: 'version.create',
            input: {
              project_id: nextProjectId,
              name: `Version ${new Date().getHours()}${new Date().getMinutes()}`,
            },
          })
        }
        navigateToView('versionSpace', { projectId: nextProjectId })
        return
      }
      case 'dashboard_risk_query':
        pushUserMessage('Which project is currently the riskiest?')
        pushAgentMessage('<div class="markdown-content"><p><strong>Payment System</strong> is currently the riskiest project because it combines one failed run, one unresolved merge, and open governance items in its active version.</p></div>')
        navigateToView('dashboard')
        return
      case 'dashboard_blockers_query':
        pushUserMessage('Show me the currently blocked releases.')
        pushAgentMessage('<div class="markdown-content"><p>Two release trains need attention: <strong>2026Q2 Release</strong> is blocked by one failed run and one pending merge, and <strong>OAuth Hardening</strong> is blocked by a missing performance lane approval.</p></div>')
        navigateToView('dashboard')
        return
      case 'refresh_system_image':
        pushUserMessage('Refresh the current project system image and report the ingest delta.')
        pushAgentMessage('<div class="markdown-content"><p>The system image refresh completed. I indexed 3 new modules, refreshed 2 outdated context objects, and detected 1 candidate relationship that should stay version-scoped until approval.</p></div>', 'Nasus Central Agent')
        return
      case 'validate_project_inputs':
        pushUserMessage('Validate the current project inputs and provider connections.')
        pushAgentMessage('<div class="markdown-content"><p>All project inputs validated successfully. Git access, document parsing, UX import, and historical asset ingestion are ready.</p></div>', 'Nasus Setup Agent')
        return
      case 'import_project_assets':
        pushUserMessage('Import the connected project assets and prepare initialization.')
        pushAgentMessage('<div class="markdown-content"><p>The project assets were imported and normalized into raw asset references. You can initialize the Official System Image next.</p></div>', 'Nasus Setup Agent')
        return
      case 'initialize_system_image': {
        await invokeToolMutation.mutateAsync({
          conversation_id: conversationId,
          tool_id: 'project.create',
          input: {
            name: extractProjectName(composerValue || 'New Quality Project'),
          },
        })
        setComposerValue('')
        return
      }
      case 'import_version_us':
        pushUserMessage('Import the latest US items into the draft version branch.')
        pushAgentMessage('<div class="markdown-content"><p>I imported 2 additional US items and classified them by affected modules and historical risk patterns.</p></div>', 'Nasus Branch Agent')
        return
      case 'assign_owners':
        pushUserMessage('Assign owners to the imported US items.')
        pushAgentMessage('<div class="markdown-content"><p>Owner suggestions are ready. They balance component expertise, current workload, and blocker distribution.</p></div>', 'Nasus Branch Agent')
        return
      case 'fork_baseline':
        pushUserMessage('Fork the baseline for the new version branch.')
        pushAgentMessage('<div class="markdown-content"><p>The version baseline was forked as a delta overlay. No full-copy duplication was required.</p></div>', 'Nasus Branch Agent')
        return
      case 'analyze_object_impact':
        pushUserMessage(`Analyze the downstream impact of ${currentObject.name}.`)
        pushAgentMessage(`<div class="markdown-content"><p>${currentObject.name} affects ${currentObject.relations.slice(0, 2).join(', ')} and directly influences the current version risk because it is referenced by ${currentUs?.id} and the active failed run.</p></div>`)
        return
      case 'promote_candidate':
        pushUserMessage(`Prepare a promotion recommendation for ${currentObject.name}.`)
        pushAgentMessage('<div class="markdown-content"><p>I prepared a promotion recommendation. The object can move from Candidate to Version Shared, but it should not enter Official until the related baseline promotion approval is resolved.</p></div>')
        return
      case 'propose_healing':
        pushUserMessage(`Propose a healing patch for ${currentRunResolved?.id}.`)
        if (currentRunResolved) {
          setRunsState((current) => ({
            ...current,
            [currentRunResolved.id]: { ...currentRunResolved, status: 'healing_proposed' },
          }))
        }
        pushAgentMessage('<div class="markdown-content"><p>I prepared a healing proposal that remaps the button selector to the new checkout confirm action and adds a DOM fallback probe.</p></div>')
        return
      case 'retry_run':
        pushUserMessage(`Retry ${currentRunResolved?.id} with the updated healing proposal.`)
        if (currentRunResolved) {
          setRunsState((current) => ({
            ...current,
            [currentRunResolved.id]: { ...currentRunResolved, status: 'reviewing' },
          }))
        }
        pushAgentMessage('<div class="markdown-content"><p>The retry was scheduled. The run is back in review with the healing proposal attached for verification.</p></div>')
        return
      case 'fallback_human':
        pushUserMessage(`Stop automated healing for ${currentRunResolved?.id} and escalate to human review.`)
        if (currentRunResolved) {
          setRunsState((current) => ({
            ...current,
            [currentRunResolved.id]: { ...currentRunResolved, status: 'needs_human_review' },
          }))
        }
        pushAgentMessage('<div class="markdown-content"><p>The run was marked for manual review. This prevents repeated healing attempts from entering a token-burning loop.</p></div>')
        return
      case 'approve_promotion':
        pushUserMessage(`Approve ${currentApprovalResolved?.title}.`)
        if (currentApprovalResolved) {
          setApprovalsState((current) => ({
            ...current,
            [currentApprovalResolved.id]: { ...currentApprovalResolved, status: 'approved' },
          }))
        }
        pushAgentMessage('<div class="markdown-content"><p>The promotion was approved and moved to the next governance step. Official baseline write-back is still gated by release closure.</p></div>', 'Nasus Policy Agent')
        return
      case 'accept_auto_merge':
        pushUserMessage(`Accept the auto-merge suggestion for ${currentApprovalResolved?.title}.`)
        if (currentApprovalResolved) {
          setApprovalsState((current) => ({
            ...current,
            [currentApprovalResolved.id]: { ...currentApprovalResolved, status: 'resolved' },
          }))
        }
        pushAgentMessage('<div class="markdown-content"><p>The auto-merge suggestion was applied. Conflict fields are resolved, and the merged resolution is ready for final approval.</p></div>', 'Nasus Policy Agent')
        return
      case 'reject_promotion':
        pushUserMessage(`Reject ${currentApprovalResolved?.title}.`)
        if (currentApprovalResolved) {
          setApprovalsState((current) => ({
            ...current,
            [currentApprovalResolved.id]: { ...currentApprovalResolved, status: 'rejected' },
          }))
        }
        pushAgentMessage('<div class="markdown-content"><p>The promotion was rejected and sent back with an explanation so the version branch can revise its candidate knowledge or delta payload.</p></div>', 'Nasus Policy Agent')
        return
      case 'generate_release_advice':
        pushUserMessage('Generate release advice for the current version.')
        setReleaseState((current) => ({ ...current, score: 78 }))
        pushAgentMessage('<div class="markdown-content"><p>The release is conditionally ready. One failed run and one pending approval remain, but the quality signal is strong enough to prepare a release gate recommendation.</p></div>')
        return
      case 'submit_release_gate':
        pushUserMessage('Submit the release gate for review.')
        pushAgentMessage('<div class="markdown-content"><p>The release gate was submitted. Governance now has a complete readiness summary, blocker list, and linked evidence package.</p></div>')
        return
      case 'interrupt_goal':
        if (payload.objectId) {
          await interruptGoalMutation.mutateAsync(payload.objectId)
        }
        return
      case 'resume_goal':
        if (payload.objectId) {
          await resumeGoalMutation.mutateAsync(payload.objectId)
        }
        return
      case 'goal_feedback':
        if (payload.objectId) {
          const feedback = composerValue.trim() || tr(
            'Please narrow the next action and explain the decision before executing another tool.',
            '请收窄下一步动作，并在执行下一个工具前解释当前决策。',
          )
          if (composerValue.trim()) {
            setComposerValue('')
          }
          await feedbackGoalMutation.mutateAsync({ goalId: payload.objectId, feedback })
        }
        return
      case 'search_docs':
        navigateToView('documentation')
        return
      default:
        pushUserMessage(`Run action: ${action}`)
        pushAgentMessage('<div class="markdown-content"><p>I routed that request from the current conversation surface. The next step is to map it to a concrete tool invocation or navigation action in the product runtime.</p></div>')
    }
  }

  async function routeUserInput(text: string) {
    if (conversationId) {
      await sendMessage(text)
      return
    }

    pushUserMessage(text)
    pushAgentMessage('<div class="markdown-content"><p>I can help with project creation, version setup, dashboard progress checks, or quality asset generation. Tell me which step you want to move forward.</p></div>')
  }

  async function handleSend() {
    const trimmed = composerValue.trim()
    if (!trimmed || isWaitingForAgent || isSending) return
    setComposerValue('')
    setIsWaitingForAgent(true)
    await new Promise((resolve) => setTimeout(resolve, 300))
    await routeUserInput(trimmed)
    setIsWaitingForAgent(false)
  }

  function handleDelegatedClick(event: MouseEvent<HTMLElement>) {
    const target = event.target as HTMLElement
    const actionTarget = target.closest<HTMLElement>('[data-action]')
    if (!actionTarget) return

    void invokeAction(actionTarget.dataset.action ?? '', {
      project: actionTarget.dataset.project,
      projectId: actionTarget.dataset.projectId,
      usId: actionTarget.dataset.usId,
      runId: actionTarget.dataset.runId,
      approvalId: actionTarget.dataset.approvalId,
      objectId: actionTarget.dataset.objectId ?? actionTarget.dataset.goalId,
    })
  }

  function seedConversation(seedView: ViewId): UIMessage[] {
    const versionNote = currentVersion ? VERSION_NOTES[currentVersion.id] : undefined
    switch (seedView) {
      case 'welcome':
        return [
          message('agent', {
            time: '09:02 AM',
            html: `
              <div class="hero-stack">
                <div class="hero-panel">
                  <div class="hero-kicker">${tr('Nasus Studio', 'Nasus 工作室')}</div>
                  <h2 class="hero-title">${tr('Build release quality with an agent-first workflow.', '用 Agent 优先的方式构建版本质量闭环。')}</h2>
                  <p class="hero-copy">${tr('Start from conversation, enter Build to create or initialize projects, use Dashboard to monitor quality closure, and use Documentation to understand the platform before entering a live workspace.', '从对话开始，在 Build 中创建或初始化项目，在 Dashboard 中查看质量闭环进展，并通过 Documentation 了解平台机制，再进入真实工作空间。')}</p>
                </div>
                <div>
                  <div class="section-heading">
                    <h3 class="section-heading-title">${tr('Choose how you want to begin', '选择你的开始方式')}</h3>
                    <p class="section-heading-copy">${tr('This is the L0 welcome layer. It should feel like a product home, not a deep task screen.', '这是 L0 欢迎层。它应该更像产品首页，而不是直接掉进深层任务界面。')}</p>
                  </div>
                  <div class="hero-grid">
                    ${heroCard('fa-solid fa-hammer', tr('Build', '创建项目'), tr('Create a project, connect Git and docs, and enter a project workspace.', '创建项目，接入 Git 与文档，并进入项目工作空间。'), 'open_build', tr('Enter Build', '进入 Build'))}
                    ${heroCard('fa-solid fa-chart-line', tr('Dashboard', '全局仪表盘'), tr('See blocked releases, open approvals, execution failures, and cross-project quality progress.', '查看阻塞发布、待审批事项、执行失败以及跨项目质量进展。'), 'open_dashboard', tr('Open Dashboard', '打开 Dashboard'))}
                    ${heroCard('fa-solid fa-book-open', tr('Documentation', '产品文档'), tr('Learn branching, system images, asset packs, governance, and release readiness.', '了解分支机制、系统画像、资产包、治理流程和发布准备度。'), 'open_documentation', tr('Read docs', '查看文档'))}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">${tr('Resume recent work', '继续最近的工作')}</h3>
                      <p class="surface-section-subtitle">${tr('Recent projects and versions should be available without dropping the user into a deep workspace by default.', '最近的项目和版本应该可以直接恢复，而不是默认把用户拉进深层工作区。')}</p>
                    </div>
                  </div>
                  <div class="collection-grid">
                    ${projects.map(projectCardMarkup).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'build':
        return [
          message('agent', {
            time: '09:12 AM',
            html: `
              <div class="surface-stack">
                <div class="hero-panel">
                  <div class="hero-kicker">${tr('Build', '创建项目')}</div>
                  <h2 class="hero-title" style="font-size:28px;">${tr('Create a new project and initialize its system image.', '创建新项目并初始化其系统画像。')}</h2>
                  <p class="hero-copy">${tr('Build is the project creation surface. It foregrounds one obvious path: define the project, import Git and requirement sources, attach UX boards and historical quality assets, then let the agent guide the initialization of the Official System Image.', 'Build 是项目创建入口。它聚焦一条清晰主线：定义项目、导入 Git 和需求资料、附加 UX 板和历史质量资产，然后由 Agent 引导完成 Official System Image 初始化。')}</p>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">${tr('Create Project', '创建项目')}</h3>
                      <p class="surface-section-subtitle">${tr('This should be the dominant visual block on the page, with both direct actions and conversational onboarding.', '这里应该是页面中最突出的视觉区块，同时支持直接操作和对话式引导。')}</p>
                    </div>
                  </div>
                  <div class="overview-grid">
                    <div class="collection-card full-span" style="padding:20px;">
                      <div class="collection-card-title" style="font-size:18px;">${tr('Start a new project space', '启动新的项目空间')}</div>
                      <div class="collection-card-copy" style="font-size:13px;">${tr('Create a project from a guided setup flow or simply ask Nasus in conversation. The agent should collect the required inputs step by step and show the setup progress as structured state.', '你可以通过引导式流程创建项目，也可以直接在对话里让 Nasus 帮你完成。Agent 会逐步收集必要输入，并把配置进度结构化展示出来。')}</div>
                      <div class="collection-card-meta">
                        ${miniChip(tr('Git repository', 'Git 仓库'), 'info')}
                        ${miniChip(tr('US documents', 'US 文档'), 'info')}
                        ${miniChip(tr('UX boards', 'UX 设计板'), 'info')}
                        ${miniChip(tr('Historical assets', '历史资产'), 'info')}
                      </div>
                      <div class="surface-actions" style="margin-top:16px;">
                        ${ghostButton(tr('Create Project', '创建项目'), 'open_project_create', 'fa-solid fa-plus')}
                        ${ghostButton(tr('Ask Agent to Guide Setup', '让 Agent 引导创建'), 'agent_create_project', 'fa-solid fa-comments')}
                      </div>
                    </div>
                    <div class="collection-card">
                      <div class="collection-card-title">${tr('Import checklist', '导入清单')}</div>
                      <div class="collection-card-copy">${tr('What the agent should collect before initialization.', 'Agent 在初始化前需要收集的信息。')}</div>
                      <div class="surface-list" style="margin-top:14px;">
                        ${surfaceRow(tr('Git repositories', 'Git 仓库'), tr('Primary service repos and optional linked UI repos', '核心服务仓库以及可选的前端关联仓库'), [miniChip(tr('required', '必需'), 'warn')])}
                        ${surfaceRow(tr('US / PRD input', 'US / PRD 输入'), tr('Requirement docs, acceptance notes, release notes', '需求文档、验收说明、发布说明'), [miniChip(tr('required', '必需'), 'warn')])}
                        ${surfaceRow(tr('UX references', 'UX 参考资料'), tr('Boards, flows, or screenshots tied to the change surface', '与变更范围相关的设计板、流程图或截图'), [miniChip(tr('recommended', '推荐'), 'info')])}
                        ${surfaceRow(tr('Historical quality assets', '历史质量资产'), tr('Existing tests, logs, flaky history, smoke packs', '已有测试、日志、历史 flaky 记录和 smoke 包'), [miniChip(tr('recommended', '推荐'), 'info')])}
                      </div>
                    </div>
                    <div class="collection-card">
                      <div class="collection-card-title">${tr('Conversation-first setup', '对话优先的创建方式')}</div>
                      <div class="collection-card-copy">${tr('Natural language should be enough to start project creation.', '用自然语言就应该足以启动项目创建。')}</div>
                      <div class="surface-list" style="margin-top:14px;">
                        ${surfaceRow(tr('User says', '用户输入'), tr('“Help me create a new project for Payment System.”', '“帮我为 Payment System 创建一个新项目。”'), [miniChip(tr('chat', '对话'), 'good')])}
                        ${surfaceRow(tr('Agent asks', 'Agent 追问'), tr('“Please provide Git repos, US docs, and UX boards.”', '“请提供 Git 仓库、US 文档和 UX 设计板。”'), [miniChip(tr('guided', '引导'), 'info')])}
                        ${surfaceRow(tr('Agent materializes', 'Agent 结构化产出'), tr('Project draft, import tasks, and system image init plan', '项目草稿、导入任务和系统画像初始化计划'), [miniChip(tr('structured', '结构化'), 'good')])}
                      </div>
                    </div>
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">${tr('Draft setups', '草稿配置')}</h3>
                      <p class="surface-section-subtitle">${tr('Build can keep unfinished project setup drafts, but it should not be the primary project browsing surface.', 'Build 可以保留未完成的项目配置草稿，但它不应承担主项目浏览页面的职责。')}</p>
                    </div>
                  </div>
                  <div class="collection-grid">
                    ${DRAFT_SETUPS.map(draftCardMarkup).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'dashboard':
        return [
          message('agent', {
            time: '09:20 AM',
            html: `
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">${tr('Global quality pulse', '全局质量脉搏')}</h3>
                      <p class="surface-section-subtitle">${tr('Dashboard is the project portfolio view. It summarizes cross-project progress, blockages, and governance pressure, then lets users enter a project space by clicking a card.', 'Dashboard 是项目全局视图。它汇总跨项目进度、阻塞项和治理压力，并允许用户通过点击卡片进入具体项目空间。')}</p>
                    </div>
                  </div>
                  <div class="surface-grid">
                    ${summaryStat(tr('Projects', '项目数'), `${dashboardQuery.data?.active_projects ?? projects.length}`, tr('Tracked in Build', '在 Build 中管理'))}
                    ${summaryStat(tr('Versions', '版本数'), `${dashboardQuery.data?.running_versions ?? versions.length}`, tr('Live release branches', '活跃发布分支'))}
                    ${summaryStat(tr('Blocked', '阻塞项'), `${dashboardQuery.data?.blocked_items ?? 0}`, tr('Needs owner action', '需要负责人处理'))}
                    ${summaryStat(tr('Failed Runs', '失败执行'), `${dashboardQuery.data?.failed_runs ?? 0}`, tr('Pending review', '等待审阅'))}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">${tr('Projects', '项目列表')}</h3>
                      <p class="surface-section-subtitle">${tr('Each project is a card. Clicking a card opens a dedicated project page rather than expanding a nested menu inside the same top-level screen.', '每个项目都是一张卡片。点击卡片会进入独立的项目页面，而不是在当前顶层页面里展开嵌套菜单。')}</p>
                    </div>
                  </div>
                  <div class="collection-grid">
                    ${projects.map(projectCardMarkup).join('')}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">${tr('Ask about progress', '用对话查询进展')}</h3>
                      <p class="surface-section-subtitle">${tr('Dashboard conversation should answer portfolio-level questions like project risk, testing progress, and pending gates.', 'Dashboard 中的对话应该回答项目组合层的问题，比如项目风险、测试进度和待处理 gate。')}</p>
                    </div>
                  </div>
                  <div class="surface-actions">
                    ${ghostButton(tr('Which project is riskiest?', '哪个项目当前风险最高？'), 'dashboard_risk_query', 'fa-solid fa-triangle-exclamation')}
                    ${ghostButton(tr('Show blocked releases', '查看被阻塞的发布'), 'dashboard_blockers_query', 'fa-solid fa-road-barrier')}
                    ${ghostButton(tr('Open governance backlog', '打开治理积压'), 'open_governance', 'fa-solid fa-gavel')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'documentation':
        return [
          message('agent', {
            time: '09:26 AM',
            html: `
              <div class="surface-stack">
                <div class="hero-panel">
                  <div class="hero-kicker">${tr('Documentation', '产品文档')}</div>
                  <h2 class="hero-title" style="font-size:28px;">${tr('Explain the system before users enter deep workflow mode.', '在用户进入深层工作流之前先解释清楚系统。')}</h2>
                  <p class="hero-copy">${tr('Documentation should feel like a first-class product area, not a footer link. It helps new users understand how Build, versions, asset packs, governance, and release readiness fit together.', 'Documentation 应该是一级产品区域，而不是页脚链接。它帮助新用户理解 Build、版本、资产包、治理和发布准备度之间的关系。')}</p>
                </div>
                <div class="collection-grid">
                  ${docs.map(docCard).join('')}
                </div>
              </div>
            `,
          }),
        ]
      case 'projectOverview': {
        const decoration = currentProject ? projectDecoration(currentProject) : null
        return [
          message('agent', {
            time: '09:40 AM',
            name: 'Nasus Central Agent',
            html: `
              <p style="margin:0 0 12px;">You are now inside the <strong>${currentProject?.name ?? 'Project'}</strong> workspace. This is the project-level command center, not the general Build page.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Project command center</h3>
                      <p class="surface-section-subtitle">Use this page to inspect connected sources, the official system image, and the versions that branch from it.</p>
                    </div>
                  </div>
                  <div class="surface-grid">
                    ${summaryStat('Baseline', decoration?.baseline ?? 'Official System Image', 'Official branch')}
                    ${summaryStat('Modules', `${decoration?.modules ?? 0}`, 'Indexed in system image')}
                    ${summaryStat('Tests', `${decoration?.tests ?? 0}`, 'Known historical assets')}
                    ${summaryStat('Versions', `${versions.length}`, currentProject?.active_version ?? 'No active version')}
                  </div>
                  <div class="surface-actions">
                    ${ghostButton('Create Version Branch', 'open_version_create', 'fa-solid fa-code-branch', { project: currentProject?.id ?? routeContext.projectId })}
                    ${ghostButton('Refresh System Image', 'refresh_system_image', 'fa-solid fa-rotate-right')}
                    ${ghostButton('Open Knowledge', 'open_knowledge_gallery', 'fa-solid fa-diagram-project', { project: currentProject?.id ?? routeContext.projectId })}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Connected sources</h3>
                      <p class="surface-section-subtitle">The project overview should summarize ingestion and source readiness before you dive into version work.</p>
                    </div>
                  </div>
                  <div class="surface-list">
                    ${(decoration?.sources ?? []).map((source) => surfaceRow(source, 'Connected and queryable', [miniChip('ready', 'good')])).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      }
      case 'projectCreate':
        return [
          message('agent', {
            time: '09:45 AM',
            name: 'Nasus Setup Agent',
            html: `
              <p style="margin:0 0 12px;">I can create a new project space from conversation or form input. Provide Git repositories, US docs, UX boards, and historical assets, and I will validate connections before initializing the <strong>Official System Image Branch</strong>.</p>
              <div class="surface-section">
                <div class="surface-section-header">
                  <div>
                    <h3 class="surface-section-title">Create Project flow</h3>
                    <p class="surface-section-subtitle">This page lives under Build, before any version work starts.</p>
                  </div>
                </div>
                <div class="form-grid">
                  <div class="form-field">
                    <div class="form-label">Project profile</div>
                    <div class="form-value">${currentProject?.name ?? 'Payment System'} / Commerce Platform</div>
                    <div class="form-note">Single enterprise deployment, multi-project model.</div>
                  </div>
                  <div class="form-field">
                    <div class="form-label">Git repositories</div>
                    <div class="form-value">2 connected repos</div>
                    <div class="form-note">payment-system, checkout-ui</div>
                  </div>
                  <div class="form-field">
                    <div class="form-label">US documents</div>
                    <div class="form-value">6 files uploaded</div>
                    <div class="form-note">PRD, acceptance notes, release notes</div>
                  </div>
                  <div class="form-field">
                    <div class="form-label">UX boards</div>
                    <div class="form-value">3 boards linked</div>
                    <div class="form-note">Checkout, refund, fallback states</div>
                  </div>
                  <div class="form-field full">
                    <div class="form-label">Historical quality assets</div>
                    <div class="form-value">2 imported packs · Validated</div>
                    <div class="form-note">Legacy smoke, regression artifacts, flaky failure history</div>
                  </div>
                </div>
                <div class="surface-actions">
                  ${ghostButton('Validate Sources', 'validate_project_inputs', 'fa-solid fa-bolt')}
                  ${ghostButton('Import Assets', 'import_project_assets', 'fa-solid fa-file-import')}
                  ${ghostButton('Initialize System Image', 'initialize_system_image', 'fa-solid fa-layer-group')}
                  ${ghostButton('Back to Build', 'open_build', 'fa-solid fa-arrow-left')}
                </div>
              </div>
            `,
          }),
        ]
      case 'versionSpace':
        return [
          message('agent', {
            time: '10:12 AM',
            html: `
              <p style="margin:0 0 12px;">The <strong>${currentVersion?.name ?? 'Version'}</strong> branch is active. This is the version-level operational center where US board, owner assignment, risk pulse, and release progress come together.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Version board</h3>
                      <p class="surface-section-subtitle">This page should exist before users jump into a single US workspace.</p>
                    </div>
                  </div>
                  <div class="surface-grid">
                    ${summaryStat('Progress', `${currentProject?.progress ?? 0}%`, versionNote?.releaseWindow ?? 'TBD')}
                    ${summaryStat('Open US', `${currentVersion?.us_total ?? 0}`, 'Across all owners')}
                    ${summaryStat('Pending approvals', `${currentVersion?.pending_approvals ?? 0}`, 'Governance queue')}
                    ${summaryStat('Pending merge', `${versionNote?.pendingMerge ?? 1}`, 'Needs manual resolution')}
                  </div>
                  <div class="surface-actions">
                    ${ghostButton('Create Version Branch', 'open_version_create', 'fa-solid fa-plus', { project: currentProject?.id ?? routeContext.projectId })}
                    ${ghostButton('Generate Version Risk', 'generate_version_risk', 'fa-solid fa-shield-halved')}
                    ${ghostButton('Release Readiness', 'open_release_readiness', 'fa-solid fa-clipboard-check')}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">US board</h3>
                      <p class="surface-section-subtitle">Every US card should be a stable entry into the personal quality workspace.</p>
                    </div>
                  </div>
                  <div class="surface-list">
                    ${usItems.map((item) => {
                      const usNote = US_NOTES[item.id]
                      return surfaceRow(
                        `${item.id} · ${item.title}`,
                        usNote?.summary ?? item.next_action,
                        [
                          miniChip(item.owner, 'info'),
                          miniChip(item.status, statusTone(item.status)),
                          miniChip(`${item.progress}%`, 'good'),
                          miniChip(item.risk, item.risk.toLowerCase() === 'high' ? 'bad' : 'warn'),
                        ],
                        `<button class="pill-chip primary" data-action="open_us_workspace" data-project="${currentProject?.id ?? routeContext.projectId}" data-us-id="${item.id}"><i class="fa-solid fa-arrow-right"></i>Open</button>`,
                      )
                    }).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'versionCreate':
        return [
          message('agent', {
            time: '10:18 AM',
            name: 'Nasus Branch Agent',
            html: `
              <p style="margin:0 0 12px;">Version creation belongs inside the project workspace, but it still precedes detailed US execution. This page launches a branch, imports US input, assigns owners, and forks the baseline.</p>
              <div class="surface-section">
                <div class="surface-section-header">
                  <div>
                    <h3 class="surface-section-title">Create Version Branch</h3>
                    <p class="surface-section-subtitle">Branch from ${currentVersion?.branch_name ?? 'main'} and seed the quality loop.</p>
                  </div>
                </div>
                <div class="form-grid">
                  <div class="form-field">
                    <div class="form-label">Version basics</div>
                    <div class="form-value">${currentVersion?.name ?? 'New Version'}</div>
                    <div class="form-note">Target release: ${versionNote?.releaseWindow ?? 'Apr 15'}</div>
                  </div>
                  <div class="form-field">
                    <div class="form-label">Source branch</div>
                    <div class="form-value">main</div>
                    <div class="form-note">Current baseline parent</div>
                  </div>
                  <div class="form-field">
                    <div class="form-label">Imported US</div>
                    <div class="form-value">${currentVersion?.us_total ?? 0} items</div>
                    <div class="form-note">Imported from product docs</div>
                  </div>
                  <div class="form-field">
                    <div class="form-label">Owner assignment</div>
                    <div class="form-value">${usItems.length} assigned</div>
                    <div class="form-note">By component expertise and workload</div>
                  </div>
                  <div class="form-field full">
                    <div class="form-label">Baseline fork preview</div>
                    <div class="form-value">Draft</div>
                    <div class="form-note">Copy-on-write delta overlay, not full duplication.</div>
                  </div>
                </div>
                <div class="surface-actions">
                  ${ghostButton('Import US', 'import_version_us', 'fa-solid fa-file-circle-plus')}
                  ${ghostButton('Assign Owners', 'assign_owners', 'fa-solid fa-user-plus')}
                  ${ghostButton('Fork Baseline', 'fork_baseline', 'fa-solid fa-code-branch')}
                  ${ghostButton('Create Version', 'create_version_branch', 'fa-solid fa-check', { project: currentProject?.id ?? routeContext.projectId })}
                </div>
              </div>
            `,
          }),
        ]
      case 'personalWorkspace': {
        const usNote = currentUs ? US_NOTES[currentUs.id] : undefined
        return [
          message('user', { time: '10:41 AM', text: `Continue quality closure for ${currentUs?.id ?? 'this US'}.` }),
          message('agent', {
            time: '10:42 AM',
            html: `
              <p style="margin:0 0 12px;">You are now in the project-level personal workspace for <strong>${currentUs?.id ?? 'US'}: ${currentUs?.title ?? 'Untitled US'}</strong>. This is the deepest L2 work surface.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">US quality closure snapshot</h3>
                      <p class="surface-section-subtitle">Current task context, latest asset pack revision, and the next actions the agent can take.</p>
                    </div>
                  </div>
                  <div class="surface-grid">
                    ${summaryStat('Progress', `${currentUs?.progress ?? 0}%`, usNote?.branch ?? currentUs?.next_action ?? '')}
                    ${summaryStat('Risk', currentUs?.risk ?? 'Medium', usNote?.impact ?? '')}
                    ${summaryStat('Revision', assetState.revision, `${assetState.scenariosDone}/${assetState.scenarioTotal} scenarios`)}
                    ${summaryStat('Pending Execution', `${assetState.pendingExecution}`, assetState.automationStatus)}
                  </div>
                  <div class="surface-actions">
                    ${ghostButton('Generate Scenarios', 'generate_scenarios', 'fa-solid fa-wand-magic-sparkles')}
                    ${ghostButton('Open Run Detail', 'open_run_detail', 'fa-solid fa-play', { project: currentProject?.id ?? routeContext.projectId, runId: currentRunResolved?.id ?? 'run_9021' })}
                    ${ghostButton('Open Release Readiness', 'open_release_readiness', 'fa-solid fa-clipboard-check', { project: currentProject?.id ?? routeContext.projectId })}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Quality Asset Pack lanes</h3>
                      <p class="surface-section-subtitle">Every lane is structured, revisable, and eventually feeds execution, governance, or release readiness.</p>
                    </div>
                  </div>
                  <div class="surface-list">
                    ${surfaceRow('Scenario Set', `Drafted from ${usNote?.impact ?? currentUs?.next_action ?? 'current context'}`, [miniChip(`${assetState.scenariosDone}/${assetState.scenarioTotal} done`, 'info')], `<button class="pill-chip primary" data-action="generate_scenarios"><i class="fa-solid fa-list-check"></i>Generate</button>`)}
                    ${surfaceRow('Case Set', `${assetState.casesDone}/${assetState.casesTotal} cases drafted`, [miniChip('Needs review', 'warn')], `<button class="pill-chip"><i class="fa-solid fa-table-list"></i>Inspect</button>`)}
                    ${surfaceRow('Automation', assetState.automationStatus, [miniChip('Playwright target', 'good')], `<button class="pill-chip" data-action="open_run_detail" data-project="${currentProject?.id ?? routeContext.projectId}" data-run-id="${currentRunResolved?.id ?? 'run_9021'}"><i class="fa-solid fa-terminal"></i>Inspect Run</button>`)}
                    ${surfaceRow('Performance', assetState.performanceStatus, [miniChip('Approval gate', 'warn')], `<button class="pill-chip" data-action="open_approval_detail" data-project="${currentProject?.id ?? routeContext.projectId}" data-approval-id="${currentApprovalResolved?.id ?? 'approval_442'}"><i class="fa-solid fa-gavel"></i>Open Gate</button>`)}
                    ${surfaceRow('Change Doc', assetState.changeDocStatus, [miniChip('Ready for release summary', 'good')], `<button class="pill-chip" data-action="open_release_readiness" data-project="${currentProject?.id ?? routeContext.projectId}"><i class="fa-solid fa-file-lines"></i>Use in Release</button>`)}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      }
      case 'knowledgeGallery':
        return [
          message('agent', {
            time: '11:05 AM',
            html: `
              <p style="margin:0 0 12px;">Knowledge is a project workspace page, not a platform homepage. This gallery helps users navigate trusted and candidate context objects tied to the selected project and version.</p>
              <div class="surface-section">
                <div class="surface-section-header">
                  <div>
                    <h3 class="surface-section-title">Knowledge objects</h3>
                    <p class="surface-section-subtitle">System, feature, and quality asset objects with branch-aware provenance.</p>
                  </div>
                </div>
                <div class="surface-list">
                  ${knowledgeObjects.map((obj) => surfaceRow(
                    `${obj.name} · ${obj.type}`,
                    `Branch: ${obj.branch} · Confidence: ${obj.confidence} · Freshness: ${obj.freshness}`,
                    obj.relations.slice(0, 2).map((name) => miniChip(name, 'info')),
                    `<button class="pill-chip primary" data-action="open_knowledge_detail" data-project="${currentProject?.id ?? routeContext.projectId}" data-object-id="${obj.id}"><i class="fa-solid fa-arrow-right"></i>Inspect</button>`,
                  )).join('')}
                </div>
              </div>
            `,
          }),
        ]
      case 'knowledgeDetail':
        return [
          message('agent', {
            time: '11:18 AM',
            html: `
              <p style="margin:0 0 12px;"><strong>${currentObject.name}</strong> is open as a branch-aware object detail page so the team can inspect evidence, relationships, and promotion readiness.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-grid">
                    ${summaryStat('Freshness', currentObject.freshness, 'Last refresh')}
                    ${summaryStat('Evidence', `${currentObject.evidence.length}`, 'Attached references')}
                    ${summaryStat('Relations', `${currentObject.relations.length}`, 'Direct graph edges')}
                    ${summaryStat('Branch', currentObject.branch, 'Current storage tier')}
                  </div>
                  <div class="surface-actions">
                    ${ghostButton('Analyze Impact', 'analyze_object_impact', 'fa-solid fa-wave-square')}
                    ${ghostButton('Promote Candidate', 'promote_candidate', 'fa-solid fa-arrow-up-right-dots')}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Relationship and evidence trail</h3>
                      <p class="surface-section-subtitle">Every object needs explainable lineage and downstream navigation.</p>
                    </div>
                  </div>
                  <div class="surface-list">
                    ${currentObject.relations.map((relation) => surfaceRow(relation, 'Direct relationship in the current context graph', [miniChip('related', 'info')])).join('')}
                    ${currentObject.evidence.map((ref) => surfaceRow(ref, 'Referenced source or generated evidence', [miniChip('evidence', 'good')])).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'runs':
        return [
          message('agent', {
            time: '11:30 AM',
            html: `
              <p style="margin:0 0 12px;">Runs should stay inside the project workspace. This page shows the canonical run list across the web execution channel.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-grid">
                    ${summaryStat('Failed', `${runs.filter((item) => item.status === 'failed').length}`, 'Needs triage')}
                    ${summaryStat('Running', `${runs.filter((item) => item.status === 'running').length}`, 'Active web execution')}
                    ${summaryStat('Passed', `${runs.filter((item) => item.status === 'passed').length}`, 'Latest stable run')}
                    ${summaryStat('Evidence', '18', 'Artifacts attached')}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Run list</h3>
                      <p class="surface-section-subtitle">Every row should open into a detailed timeline and evidence workspace.</p>
                    </div>
                  </div>
                  <div class="surface-list">
                    ${runs.map((run) => surfaceRow(
                      `${run.id} · ${run.title}`,
                      `${run.channel === 'web_runner' ? 'Web Runner' : 'Runner'} · ${run.started_at} · ${run.summary}`,
                      [
                        miniChip(run.status, run.status === 'failed' ? 'bad' : 'good'),
                        miniChip(run.channel === 'web_runner' ? 'web' : 'edge', 'info'),
                      ],
                      `<button class="pill-chip primary" data-action="open_run_detail" data-project="${currentProject?.id ?? routeContext.projectId}" data-run-id="${run.id}"><i class="fa-solid fa-arrow-right"></i>Open</button>`,
                    )).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'runDetail':
        return [
          message('agent', {
            time: '11:42 AM',
            html: `
              <p style="margin:0 0 12px;">Run detail should carry the full failure analysis loop: timeline, logs, evidence, healing proposal, and fallback-to-human threshold.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-grid">
                    ${summaryStat('Failure', currentRunDetail?.failure_summary ?? currentRunResolved?.summary ?? 'No failure summary', 'Current primary fingerprint')}
                    ${summaryStat('Healing', currentRunDetail?.healing_status ?? currentRunResolved?.status ?? 'Not Proposed', 'Proposal status')}
                    ${summaryStat('Evidence', `${currentRunDetail?.evidence.length ?? 7}`, 'Artifacts available')}
                    ${summaryStat('Trace', 'Ready', 'trace-checkout-9021.zip')}
                  </div>
                  <div class="surface-actions">
                    ${ghostButton('Propose Healing Patch', 'propose_healing', 'fa-solid fa-syringe')}
                    ${ghostButton('Retry Run', 'retry_run', 'fa-solid fa-rotate')}
                    ${ghostButton('Fallback to Human', 'fallback_human', 'fa-solid fa-user-check')}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Timeline</h3>
                      <p class="surface-section-subtitle">This is where the team learns what actually happened in execution.</p>
                    </div>
                  </div>
                  <div class="timeline-list">
                    ${(currentRunDetail?.timeline ?? [
                      'Queued with checkout regression pack.',
                      'Started browser session against release candidate.',
                      'Observed redirect mismatch on saved-card confirmation.',
                    ]).map((item, index, arr) => `<div class="timeline-item"><div class="timeline-dot ${index === arr.length - 1 ? 'bad' : ''}"></div><div class="timeline-content"><div class="timeline-title">${index === 0 ? 'Run queued' : index === arr.length - 1 ? 'Failure observed' : 'Execution step'}</div><div class="timeline-text">${item}</div></div></div>`).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'governance':
        return [
          message('agent', {
            time: '12:00 PM',
            name: 'Nasus Policy Agent',
            html: `
              <p style="margin:0 0 12px;">Governance belongs inside the project workspace, but it separates queue view from item detail. The list page shows approvals, pending merges, and policy-blocked items at a glance.</p>
              <div class="surface-section">
                <div class="surface-section-header">
                  <div>
                    <h3 class="surface-section-title">Pending governance items</h3>
                    <p class="surface-section-subtitle">Approvals, promotions, local capability requests, and merge conflicts all belong here.</p>
                  </div>
                </div>
                <div class="surface-list">
                  ${approvals.map((approval) => surfaceRow(
                    approval.title,
                    approval.summary,
                    [
                      miniChip(approval.status, approval.status.includes('waiting') ? 'warn' : 'good'),
                      miniChip('approval', 'info'),
                    ],
                    `<button class="pill-chip primary" data-action="open_approval_detail" data-project="${currentProject?.id ?? routeContext.projectId}" data-approval-id="${approval.id}"><i class="fa-solid fa-arrow-right"></i>Review</button>`,
                  )).join('')}
                </div>
                <div class="surface-actions">
                  ${ghostButton('Open Release Readiness', 'open_release_readiness', 'fa-solid fa-clipboard-check')}
                </div>
              </div>
            `,
          }),
        ]
      case 'approvalDetail':
        return [
          message('agent', {
            time: '12:08 PM',
            name: 'Nasus Policy Agent',
            html: `
              <p style="margin:0 0 12px;">This page must resolve more than a yes/no decision. It needs explicit merge detail, policy reason, and evidence links so the user understands what they are approving.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-grid">
                    ${summaryStat('Status', currentApprovalResolved?.status ?? 'Waiting Approval', 'Quality lead sign-off')}
                    ${summaryStat('Conflict fields', `${currentApprovalDetail?.conflict_fields.length ?? 2}`, 'Auto merge available')}
                  </div>
                  <div class="surface-note" style="margin-top:16px;">
                    ${currentApprovalDetail?.policy_reason ?? 'Version Shared promotion is allowed, but Official baseline write-back must remain blocked until release closure.'}
                  </div>
                  <div class="surface-actions">
                    ${ghostButton('Approve Promotion', 'approve_promotion', 'fa-solid fa-thumbs-up')}
                    ${ghostButton('Accept Auto Merge', 'accept_auto_merge', 'fa-solid fa-code-merge')}
                    ${ghostButton('Reject', 'reject_promotion', 'fa-solid fa-ban')}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">3-way merge detail</h3>
                      <p class="surface-section-subtitle">This page avoids reducing conflict resolution to a generic text explanation.</p>
                    </div>
                  </div>
                  <div class="split-columns">
                    <div class="compare-card">
                      <h4>Base</h4>
                      <ul>
                        <li>Selector path: <code>Checkout.SubmitButton</code></li>
                        <li>Quality profile risk: medium</li>
                        <li>Scenario branch: official</li>
                      </ul>
                    </div>
                    <div class="compare-card">
                      <h4>Version branch</h4>
                      <ul>
                        ${(currentApprovalDetail?.conflict_fields ?? [
                          'Selector path updated to Checkout.ConfirmAction',
                          'Quality profile risk elevated to high',
                          'Candidate automation draft attached',
                        ]).map((field) => `<li>${field}</li>`).join('')}
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            `,
          }),
        ]
      case 'releaseReadiness':
        return [
          message('agent', {
            time: '12:18 PM',
            html: `
              <p style="margin:0 0 12px;">Release readiness deserves a dedicated page so quality leads can see score, blockers, open approvals, and unresolved execution problems in one place.</p>
              <div class="surface-stack">
                <div class="surface-section">
                  <div class="surface-grid">
                    ${summaryStat('Score', `${currentReleaseReadiness?.score ?? releaseState.score}`, 'Composite release score')}
                    ${summaryStat('Blockers', `${currentReleaseReadiness?.blockers ?? releaseState.blockers}`, currentReleaseReadiness?.execution_health ?? releaseState.executionHealth)}
                    ${summaryStat('Open approvals', `${currentReleaseReadiness?.approvals_open ?? releaseState.approvalsOpen}`, 'Promotion + capability')}
                    ${summaryStat('Pending merge', `${currentReleaseReadiness?.pending_merge ?? releaseState.pendingMerge}`, 'Conflict resolution required')}
                  </div>
                  <div class="surface-actions">
                    ${ghostButton('Generate Release Advice', 'generate_release_advice', 'fa-solid fa-wand-magic-sparkles')}
                    ${ghostButton('Submit Release Gate', 'submit_release_gate', 'fa-solid fa-paper-plane')}
                    ${ghostButton('Open Approval Detail', 'open_approval_detail', 'fa-solid fa-arrow-right', { project: currentProject?.id ?? routeContext.projectId, approvalId: currentApprovalResolved?.id ?? 'approval_442' })}
                  </div>
                </div>
                <div class="surface-section">
                  <div class="surface-section-header">
                    <div>
                      <h3 class="surface-section-title">Blocking issues</h3>
                      <p class="surface-section-subtitle">These should be visible without drilling into multiple pages.</p>
                    </div>
                  </div>
                  <div class="surface-list">
                    ${(currentReleaseReadiness?.blocker_items ?? [
                      'RUN-9021 failed on web runner',
                      'Scenario pack approval still waiting',
                      'One performance lane still waiting confirmation',
                    ]).map((item) => surfaceRow(item, 'Release blocker', [miniChip('blocker', 'warn')])).join('')}
                  </div>
                </div>
              </div>
            `,
          }),
        ]
    }
  }

  function renderPanelContent() {
    const projectDecorationValue = currentProject ? projectDecoration(currentProject) : null
    const versionNote = currentVersion ? VERSION_NOTES[currentVersion.id] : undefined
    const usNote = currentUs ? US_NOTES[currentUs.id] : undefined
    const tab = panelTabs[viewId]

    const views: Record<ViewId, Record<string, string>> = {
      welcome: {
        activity: panelActivity(['Platform opened', 'Payment System remains active', '2 versions need review']),
        tips: `
          <div class="panel-section-label">${tr('Suggested Starts', '推荐开始方式')}</div>
          ${moduleItem(tr('Create a project from conversation', '通过对话创建项目'), 'agent')}
          ${moduleItem(tr('Use Build to start a new project', '使用 Build 启动新项目'), 'build')}
          ${moduleItem(tr('Use Dashboard to inspect active projects', '使用 Dashboard 查看活跃项目'), 'ops')}
        `,
        status: `
          <div class="panel-section-label">${tr('Platform Status', '平台状态')}</div>
          ${moduleItem(tr('Core services healthy', '核心服务健康'), 'ok')}
          ${moduleItem(tr('SSE streaming connected', 'SSE 流式连接已建立'), 'live')}
          ${moduleItem(tr('Web agent runtime available', 'Web Agent 运行时可用'), 'agent')}
        `,
      },
      build: {
        projects: `
          <div class="panel-section-label">${tr('Build Readiness', '创建准备度')}</div>
          ${moduleItem(tr('Create Project is the primary action', '创建项目是当前主操作'), 'primary')}
          ${moduleItem(tr('Conversation-guided import supported', '支持对话引导式导入'), 'agent')}
          ${moduleItem(tr('System image init follows validation', '系统画像初始化会在校验后执行'), 'flow')}
        `,
        imports: `
          <div class="panel-section-label">${tr('Import Lanes', '导入通道')}</div>
          ${moduleItem(tr('Git repositories', 'Git 仓库'), 'git')}
          ${moduleItem(tr('US and PRD docs', 'US 与 PRD 文档'), 'docs')}
          ${moduleItem(tr('UX boards and screenshots', 'UX 设计板与截图'), 'ux')}
          ${moduleItem(tr('Historical quality assets', '历史质量资产'), 'qa')}
        `,
        health: `
          <div class="panel-section-label">${tr('Setup Drafts', '配置草稿')}</div>
          ${DRAFT_SETUPS.map((draft) => moduleItem(draft.title, 'draft')).join('')}
        `,
      },
      dashboard: {
        alerts: `
          <div class="panel-section-label">${tr('Alerts', '告警')}</div>
          ${moduleItem(tr('RUN-9021 still failed', 'RUN-9021 仍然失败'), 'high')}
          ${moduleItem(tr('Scenario pack waiting approval', '场景资产包仍在等待审批'), 'warn')}
          ${moduleItem(tr('1 release gate needs review', '1 个发布闸口等待审阅'), 'review')}
        `,
        progress: `
          <div class="panel-section-label">${tr('Progress', '进度')}</div>
          ${projects.map((project) => moduleItem(`${project.name} · ${project.progress}%`, project.active_version)).join('')}
        `,
        activity: panelActivity(['Dashboard risk pulse refreshed', 'Governance backlog queried', 'Project health rollup updated']),
      },
      documentation: {
        topics: `
          <div class="panel-section-label">${tr('Topics', '主题')}</div>
          ${docs.map((doc) => moduleItem(doc.title, doc.category.toUpperCase())).join('')}
        `,
        templates: `
          <div class="panel-section-label">${tr('Templates', '模板')}</div>
          ${moduleItem(tr('Project setup checklist', '项目配置清单'), 'template')}
          ${moduleItem(tr('Version launch checklist', '版本启动清单'), 'template')}
          ${moduleItem(tr('Release readiness summary', '发布准备度摘要'), 'template')}
        `,
        updates: panelActivity(['Branching guide revised', 'Quality Asset Pack reference updated', 'Release readiness guide refreshed']),
      },
      projectOverview: {
        context: `
          <div class="panel-section-label">Project Context</div>
          ${moduleItem(projectDecorationValue?.baseline ?? 'Official System Image', 'official')}
          ${moduleItem(`${projectDecorationValue?.modules ?? 0} modules indexed`, 'graph')}
          ${moduleItem(`${projectDecorationValue?.tests ?? 0} historical tests known`, 'qa')}
        `,
        versions: `
          <div class="panel-section-label">Versions</div>
          ${versions.map((item) => moduleItem(`${item.name} · ${item.branch_name}`, item.status.toUpperCase())).join('')}
        `,
        activity: panelActivity(['System image refreshed 1h ago', 'Version overlay active', 'No provider degradation detected']),
      },
      projectCreate: {
        context: `
          <div class="panel-section-label">Setup Status</div>
          ${moduleItem('2 repos connected', 'git')}
          ${moduleItem('6 docs loaded', 'docs')}
          ${moduleItem('3 boards linked', 'ux')}
        `,
        assets: `
          <div class="panel-section-label">Imported Assets</div>
          ${moduleItem('Legacy smoke pack', 'qa')}
          ${moduleItem('Regression suite snapshot', 'qa')}
          ${moduleItem('Checkout board', 'ux')}
        `,
        activity: panelActivity(['Source validation completed', 'Import bundle staged', 'System image init waiting']),
      },
      versionSpace: {
        board: `
          <div class="panel-section-label">US Board Pulse</div>
          ${usItems.map((item) => moduleItem(`${item.id} · ${item.owner}`, item.status.toUpperCase())).join('')}
        `,
        context: `
          <div class="panel-section-label">Version Context</div>
          ${moduleItem(currentVersion?.branch_name ?? 'release/branch', 'branch')}
          ${moduleItem(`${currentVersion?.pending_approvals ?? 0} open approvals`, 'warn')}
          ${moduleItem(`${versionNote?.pendingMerge ?? 1} pending merge`, 'warn')}
        `,
        activity: panelActivity(['US board refreshed', 'Version risk recomputed', 'Release readiness still blocked']),
      },
      versionCreate: {
        summary: `
          <div class="panel-section-label">Branch Summary</div>
          ${moduleItem(currentVersion?.branch_name ?? 'release/target', 'target')}
          ${moduleItem(`${currentVersion?.us_total ?? 0} imported US`, 'us')}
          ${moduleItem('Draft baseline overlay', 'fork')}
        `,
        owners: `
          <div class="panel-section-label">Owner Assignment</div>
          ${usItems.map((item) => moduleItem(`${item.id} · ${item.owner}`, 'assigned')).join('')}
        `,
        activity: panelActivity(['US import staged', 'Owner suggestion ready', 'Fork preview generated']),
      },
      personalWorkspace: {
        assets: `
          <div class="panel-section-label">Asset Pack</div>
          ${moduleItem(`Scenario Set · ${assetState.scenariosDone}/${assetState.scenarioTotal}`, 'draft')}
          ${moduleItem(`Case Set · ${assetState.casesDone}/${assetState.casesTotal}`, 'draft')}
          ${moduleItem(`Automation · ${assetState.automationStatus}`, 'playwright')}
          ${moduleItem(`Performance · ${assetState.performanceStatus}`, 'gate')}
        `,
        context: `
          <div class="panel-section-label">US Context</div>
          ${moduleItem(`${currentUs?.id ?? 'US'} · ${currentUs?.title ?? 'Untitled'}`, (currentUs?.risk ?? 'Medium').toUpperCase())}
          ${moduleItem(usNote?.impact ?? currentUs?.next_action ?? '', 'impact')}
          ${moduleItem(usNote?.branch ?? 'feature/branch', 'branch')}
        `,
        activity: panelActivity(['US context refreshed', 'Scenarios ready for review', 'Run queued from current pack']),
      },
      knowledgeGallery: {
        graph: `
          <div class="panel-section-label">Graph Nodes</div>
          ${knowledgeObjects.map((item) => moduleItem(`${item.name} · ${item.type}`, item.branch.toUpperCase())).join('')}
        `,
        branches: `
          <div class="panel-section-label">Branch Tiers</div>
          ${moduleItem('Official', 'trusted')}
          ${moduleItem('Version Shared', 'working')}
          ${moduleItem('Candidate', 'pending')}
        `,
        activity: panelActivity(['Object freshness updated', 'Candidate pack detected', 'One promotion recommendation queued']),
      },
      knowledgeDetail: {
        context: `
          <div class="panel-section-label">Object Context</div>
          ${moduleItem(currentObject.name, currentObject.type.toUpperCase())}
          ${moduleItem(`Confidence ${currentObject.confidence}`, 'score')}
          ${moduleItem(`Branch ${currentObject.branch}`, 'branch')}
        `,
        evidence: `
          <div class="panel-section-label">Evidence</div>
          ${currentObject.evidence.map((item) => moduleItem(item, 'evidence')).join('')}
        `,
        history: panelActivity(['Object opened from gallery', 'Promotion advice prepared', 'Evidence lineage loaded']),
      },
      runs: {
        active: `
          <div class="panel-section-label">Run Queue</div>
          ${runs.map((item) => moduleItem(`${item.id} · ${item.status}`, item.channel === 'web_runner' ? 'web' : 'edge')).join('')}
        `,
        channels: `
          <div class="panel-section-label">Channels</div>
          ${moduleItem('Web Runner', 'shared')}
          ${moduleItem('Canonical execution lane', 'runner')}
        `,
        activity: panelActivity(['Run backlog refreshed', 'Healing threshold healthy', 'Evidence manifests available']),
      },
      runDetail: {
        evidence: `
          <div class="panel-section-label">Artifacts</div>
          ${moduleItem('Trace · trace-checkout-9021.zip', 'trace')}
          ${moduleItem('7 evidence items', 'bundle')}
          ${moduleItem(currentRunResolved?.summary ?? 'Failure summary', 'failure')}
        `,
        trace: `
          <div class="panel-section-label">Trace Context</div>
          ${moduleItem(currentRunResolved?.started_at ?? '2026-03-27 17:50', 'env')}
          ${moduleItem('Web Runner', 'channel')}
          ${moduleItem(currentRunResolved?.status ?? 'reviewing', 'healing')}
        `,
        activity: panelActivity(['Failure fingerprint loaded', 'Trace bundle attached', 'Healing still pending']),
      },
      governance: {
        pending: `
          <div class="panel-section-label">Pending Items</div>
          ${Object.values(approvalsState).map((item) => moduleItem(item.title, item.status.toUpperCase())).join('')}
        `,
        policy: `
          <div class="panel-section-label">Policy Gates</div>
          ${moduleItem('Baseline promotion requires quality lead sign-off', 'policy')}
          ${moduleItem('Release gate requires governance review', 'policy')}
        `,
        activity: panelActivity(['Approval queue opened', 'Policy reason loaded', 'Release gate still blocked']),
      },
      approvalDetail: {
        diff: `
          <div class="panel-section-label">Conflict Payload</div>
          ${(currentApprovalDetail?.conflict_fields ?? ['Selector path conflict', 'Risk level conflict', 'Auto merge available']).map((field) => moduleItem(field, 'field')).join('')}
        `,
        policy: `
          <div class="panel-section-label">Approval Policy</div>
          ${moduleItem('Quality lead sign-off', 'required')}
          ${moduleItem(currentApprovalDetail?.policy_reason ?? currentApprovalResolved?.summary ?? 'Promotion scope', 'scope')}
        `,
        activity: panelActivity(['Detail opened from governance queue', '3-way merge shown', 'No final resolution yet']),
      },
      releaseReadiness: {
        blockers: `
          <div class="panel-section-label">Blockers</div>
          ${(currentReleaseReadiness?.blocker_items ?? ['RUN-9021 failed on web runner', 'Scenario pack waiting approval', 'Performance lane still pending']).map((item) => moduleItem(item, 'run')).join('')}
        `,
        signals: `
          <div class="panel-section-label">Signals</div>
          ${moduleItem(`Score ${currentReleaseReadiness?.score ?? releaseState.score}`, 'score')}
          ${moduleItem(currentReleaseReadiness?.status ?? releaseState.status, 'status')}
          ${moduleItem(currentReleaseReadiness?.execution_health ?? releaseState.executionHealth, 'exec')}
        `,
        activity: panelActivity(['Release advice generated', 'Approval queue referenced', 'No gate submission accepted yet']),
      },
    }

    return views[viewId]?.[tab] ?? ''
  }

  const meta = viewMeta()
  const inWorkspace = WORKSPACE_VIEWS.has(viewId)

  function sidebarNav() {
    if (!inWorkspace) {
      return (
        <>
          <div className="sidebar-section-label" style={{ paddingTop: 8 }}>{tr('Studio', '工作室')}</div>
          <button className={`sidebar-nav-item ${viewId === 'welcome' ? 'active' : ''}`} onClick={() => navigateToView('welcome')}>
            <i className="fa-solid fa-house" />
            {tr('Welcome', '欢迎')}
          </button>
          <div className="sidebar-section-label">{tr('Explore', '探索')}</div>
          {[
            ['build', 'fa-solid fa-hammer', tr('Build', '创建项目')],
            ['dashboard', 'fa-solid fa-chart-line', tr('Dashboard', '全局仪表盘')],
            ['documentation', 'fa-solid fa-book-open', tr('Documentation', '产品文档')],
          ].map(([id, icon, label]) => (
            <button
              className={`sidebar-nav-item ${viewId === id ? 'active' : ''}`}
              key={id}
              onClick={() => navigateToView(id as ViewId)}
            >
              <i className={icon} />
              {label}
            </button>
          ))}
        </>
      )
    }

    const decoration = currentProject ? projectDecoration(currentProject) : null
    return (
      <>
        <button className="sidebar-parent-link" onClick={() => navigateToView('dashboard')}>
          <i className="fa-solid fa-chevron-left" />
          {tr('Dashboard', '全局仪表盘')}
        </button>
        <div className="workspace-context">
          <div className="workspace-context-title">{currentProject?.name ?? 'Project'}</div>
          <div className="workspace-context-meta">{currentVersion?.name ?? 'Version'} · {currentUs?.id ?? 'US'} · {decoration?.baseline ?? 'Official System Image'}</div>
          <div className="workspace-context-badges">
            <span className="workspace-badge"><i className="fa-solid fa-wave-square" />{decoration?.overallRisk ?? 'Stable'}</span>
            <span className="workspace-badge"><i className="fa-solid fa-circle-nodes" />{decoration?.modules ?? 0} modules</span>
            <span className="workspace-badge"><i className="fa-solid fa-flask-vial" />{decoration?.tests ?? 0} tests</span>
          </div>
        </div>
        <div className="sidebar-section-label">{tr('Workspace', '工作空间')}</div>
        {[
          ['projectOverview', 'fa-solid fa-layer-group', tr('Project Overview', '项目概览')],
          ['versionSpace', 'fa-solid fa-code-branch', tr('Version Space', '版本空间')],
          ['personalWorkspace', 'fa-regular fa-user', tr('Personal Workspace', '个人工作台')],
          ['knowledgeGallery', 'fa-solid fa-diagram-project', tr('Knowledge', '知识图谱')],
          ['runs', 'fa-solid fa-play', tr('Runs', '执行记录')],
          ['governance', 'fa-solid fa-stamp', tr('Governance', '治理审批')],
        ].map(([id, icon, label]) => {
          const active = (id === 'versionSpace' && (viewId === 'versionSpace' || viewId === 'versionCreate'))
            || (id === 'knowledgeGallery' && (viewId === 'knowledgeGallery' || viewId === 'knowledgeDetail'))
            || (id === 'runs' && (viewId === 'runs' || viewId === 'runDetail'))
            || (id === 'governance' && (viewId === 'governance' || viewId === 'approvalDetail' || viewId === 'releaseReadiness'))
            || viewId === id
          return (
            <button
              className={`sidebar-nav-item ${active ? 'active' : ''}`}
              key={id}
              onClick={() => navigateToView(id as ViewId)}
            >
              <i className={icon} />
              {label}
            </button>
          )
        })}
        <div className="sidebar-section-label">{tr('Active US', '当前 US')}</div>
        {usItems.map((item) => (
          <button
            className={`us-item ${routeContext.usId === item.id ? 'active' : ''}`}
            key={item.id}
            onClick={() => navigateToView('personalWorkspace', { usId: item.id })}
          >
            <span className={`us-dot ${item.risk.toLowerCase() === 'high' ? 'amber' : item.risk.toLowerCase() === 'medium' ? 'gray' : 'green'}`} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.id}: {item.title}</span>
          </button>
        ))}
      </>
    )
  }

  const panelTabOptions = PANEL_TABS[viewId]

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%' }} onClick={handleDelegatedClick}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo" id="home-link" style={{ cursor: 'pointer' }} onClick={() => navigateToView('welcome')}>
            Nasus Studio
            <span className="sidebar-version">v</span>
          </div>
        </div>
        <nav className="sidebar-nav custom-scrollbar">
          {sidebarNav()}
        </nav>
        <div className="sidebar-footer">
          <button className="sidebar-footer-link">
            <i className="fa-regular fa-lightbulb" />
            {tr("What's new", '最新内容')}
          </button>
          <button className="sidebar-footer-link">
            <i className="fa-solid fa-key" />
            {tr('Get API key', '获取 API Key')}
          </button>
          <button className={`sidebar-footer-link ${settingsOpen ? 'active' : ''}`} onClick={() => setSettingsOpen((current) => !current)}>
            <i className="fa-solid fa-gear" />
            {tr('Settings', '设置')}
          </button>
          <div className="sidebar-user">
            <img src="https://ui-avatars.com/api/?name=US&background=8ab4f8&color=131314&size=24" alt="User" className="sidebar-user-avatar" />
            <span className="sidebar-user-name">kunben7777@gmai...</span>
          </div>
        </div>
      </aside>

      <div className="main-content">
        <header className="main-header">
          <div className="main-header-title" dangerouslySetInnerHTML={{ __html: `<h1 style="margin:0;font-size:15px;font-weight:500;">${meta.title}</h1>${meta.badge}` }} />
          <div className="header-actions">
            <button className="header-action-btn"><i className="fa-solid fa-share-nodes" /></button>
            <button className="header-action-btn"><i className="fa-solid fa-code" /></button>
            <button className="header-action-btn"><i className="fa-solid fa-ellipsis" /></button>
          </div>
        </header>

        <div className="chat-area custom-scrollbar">
          <div className="chat-messages">
            <div className="time-separator"><span>Today</span></div>
            {currentConversation.map((item, index) => (
              <Fragment key={`${conversationKey(viewId)}:${index}`}>{renderPrototypeMessage(item)}</Fragment>
            ))}
            {isWaitingForAgent ? (
              <div className="message agent message-in">
                <div className="agent-avatar" dangerouslySetInnerHTML={{ __html: agentIcon() }} />
                <div className="message-body" style={{ flex: 1, maxWidth: '85%' }}>
                  <div className="message-meta"><span className="name">Nasus Agent</span><span className="time">{formatTime()}</span></div>
                  <div className="message-bubble">
                    <div className="typing-dots">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="input-area">
          <div className="input-wrapper">
            <div className={`input-container ${composerValue ? 'focused' : ''}`}>
              <div className="input-inner">
                <textarea
                  className="input-textarea"
                  placeholder={meta.placeholder}
                  value={composerValue}
                  rows={1}
                  onChange={(event) => setComposerValue(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      void handleSend()
                    }
                  }}
                />
                <div className="input-tools">
                  <div className="input-tools-left">
                    {viewId === 'dashboard' ? (
                      <>
                        <button className="pill-chip" type="button" onClick={() => void invokeAction('dashboard_risk_query')}><i className="fa-solid fa-triangle-exclamation" />{tr('Which project is riskiest?', '哪个项目风险最高？')}</button>
                        <button className="pill-chip" type="button" onClick={() => void invokeAction('dashboard_blockers_query')}><i className="fa-solid fa-road-barrier" />{tr('Show blocked releases', '查看阻塞发布')}</button>
                      </>
                    ) : null}
                    {viewId === 'personalWorkspace' ? (
                      <>
                        <button className="pill-chip primary" type="button" onClick={() => void invokeAction('generate_scenarios')}><i className="fa-solid fa-list-check" />{tr('Generate Scenarios', '生成测试场景')}</button>
                        <button className="pill-chip" type="button" onClick={() => void invokeAction('open_run_detail')}><i className="fa-solid fa-play" />{tr('Open Run Detail', '打开执行详情')}</button>
                      </>
                    ) : null}
                  </div>
                  <button className="send-btn" type="button" disabled={!composerValue.trim() || isWaitingForAgent} onClick={() => void handleSend()}>
                    <i className="fa-solid fa-paper-plane" />
                  </button>
                </div>
              </div>
            </div>
            <div className="input-footer">
              <span>{tr('Agent-first workspace input', 'Agent 优先的工作台输入')}</span>
              <span className="status-indicator"><span className="status-dot" />{tr('live', '在线')}</span>
            </div>
          </div>
        </div>
      </div>

      <aside className="right-panel">
        <div className="panel-header">
          <h2>{meta.panelTitle}</h2>
          <button type="button">{tr('Inspect', '查看')}</button>
        </div>
        <div className="panel-tabs">
          <div className="panel-tab-group">
            {panelTabOptions.map((tab) => (
              <button
                className={`panel-tab ${panelTabs[viewId] === tab.id ? 'active' : ''}`}
                key={tab.id}
                type="button"
                onClick={() => setPanelTabs((current) => ({ ...current, [viewId]: tab.id }))}
              >
                {language === 'zh'
                  ? {
                      Activity: '动态',
                      Tips: '提示',
                      Status: '状态',
                      Projects: '项目',
                      Imports: '导入',
                      Health: '健康度',
                      Alerts: '告警',
                      Progress: '进度',
                      Topics: '主题',
                      Templates: '模板',
                      Updates: '更新',
                      Context: '上下文',
                      Versions: '版本',
                      Assets: '资产',
                      Board: '看板',
                      Summary: '摘要',
                      Owners: '负责人',
                      Graph: '图谱',
                      Branches: '分支',
                      Evidence: '证据',
                      History: '历史',
                      Active: '进行中',
                      Channels: '通道',
                      Trace: '追踪',
                      Pending: '待处理',
                      Policy: '策略',
                      Diff: '差异',
                      Blockers: '阻塞项',
                      Signals: '信号',
                      Queue: '队列',
                      Grants: '授权',
                      Sync: '同步',
                    }[tab.label] ?? tab.label
                  : tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="panel-content custom-scrollbar" dangerouslySetInnerHTML={{ __html: renderPanelContent() }} />
      </aside>

      {settingsOpen ? (
        <div className="settings-popover-layer" onClick={() => setSettingsOpen(false)}>
          <div className="settings-popover-anchor" onClick={(event) => event.stopPropagation()}>
            <div className="settings-popover">
              <div className="settings-menu">
                <button
                  className={`settings-menu-item ${settingsPanel === 'model' ? 'active' : ''}`}
                  type="button"
                  onClick={() => setSettingsPanel((current) => (current === 'model' ? null : 'model'))}
                >
                  <span className="settings-menu-icon"><i className="fa-solid fa-sparkles" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Model configuration', '模型配置')}</span>
                    <span className="settings-menu-detail">{currentModelDetail}</span>
                  </span>
                  <i className="fa-solid fa-chevron-right settings-menu-chevron" />
                </button>

                <button
                  className={`settings-menu-item ${settingsPanel === 'theme' ? 'active' : ''}`}
                  type="button"
                  onClick={() => setSettingsPanel((current) => (current === 'theme' ? null : 'theme'))}
                >
                  <span className="settings-menu-icon"><i className="fa-regular fa-lightbulb" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Theme', '主题')}</span>
                    <span className="settings-menu-detail">
                      {theme === 'system'
                        ? tr('System', '跟随系统')
                        : theme === 'light'
                          ? tr('Light', '浅色')
                          : tr('Dark', '深色')}
                    </span>
                  </span>
                  <i className="fa-solid fa-chevron-right settings-menu-chevron" />
                </button>

                <button
                  className={`settings-menu-item ${settingsPanel === 'language' ? 'active' : ''}`}
                  type="button"
                  onClick={() => setSettingsPanel((current) => (current === 'language' ? null : 'language'))}
                >
                  <span className="settings-menu-icon"><i className="fa-solid fa-language" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Language', '语言')}</span>
                    <span className="settings-menu-detail">{language === 'zh' ? '中文' : 'English'}</span>
                  </span>
                  <i className="fa-solid fa-chevron-right settings-menu-chevron" />
                </button>

                <button
                  className={`settings-menu-item ${settingsPanel === 'notifications' ? 'active' : ''}`}
                  type="button"
                  onClick={() => setSettingsPanel((current) => (current === 'notifications' ? null : 'notifications'))}
                >
                  <span className="settings-menu-icon"><i className="fa-regular fa-bell" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Applet notifications', '工作台通知')}</span>
                    <span className="settings-menu-detail">
                      {notificationMode === 'all'
                        ? tr('All updates', '全部更新')
                        : notificationMode === 'muted'
                          ? tr('Mute', '静默')
                          : tr('Important only', '仅重要通知')}
                    </span>
                  </span>
                  <i className="fa-solid fa-chevron-right settings-menu-chevron" />
                </button>

                <div className="settings-menu-divider" />

                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('status')}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-chart-bar" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('View status', '查看状态')}</span>
                  </span>
                </button>

                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('terms')}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-file-lines" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Terms of service', '服务条款')}</span>
                  </span>
                </button>

                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('privacy')}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-shield" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Privacy policy', '隐私政策')}</span>
                  </span>
                </button>

                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('feedback')}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-flag" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Send feedback', '发送反馈')}</span>
                  </span>
                </button>

                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('billing')}>
                  <span className="settings-menu-icon"><i className="fa-solid fa-flask" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Billing support', '计费支持')}</span>
                  </span>
                </button>
              </div>
            </div>

            {settingsPanel ? (
              <div className="settings-subpanel-shell">
                {renderSettingsSubmenu()}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
