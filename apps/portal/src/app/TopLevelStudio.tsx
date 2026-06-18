/* eslint-disable react-hooks/immutability, react-hooks/exhaustive-deps */
import { Fragment, useEffect, useMemo, useState } from 'react'
import type { MouseEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { api } from '../features/api'
import { useConversation } from '../hooks/useConversation'
import {
  DRAFT_SETUPS,
  agentIcon,
  draftCardMarkup,
  formatTime,
  ghostButton,
  heroCard,
  message,
  miniChip,
  moduleItem,
  panelActivity,
  projectCardMarkup,
  renderPrototypeMessage,
  statusTone,
  summaryStat,
  surfaceRow,
  topLevelViewMeta,
  type UIMessage,
  type Translator,
} from './prototypeShared'
import type {
  ModelPreset,
  ProviderName,
  SettingsConnectionResult,
  StudioSettingsConnectionTestRequest,
} from '../features/types'

type TopLevelViewId = 'welcome' | 'build' | 'dashboard'
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

const PANEL_TABS: Record<TopLevelViewId, { id: TabId; label: string }[]> = {
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
}

const DEFAULT_PANEL_TABS: Record<TopLevelViewId, TabId> = {
  welcome: 'activity',
  build: 'projects',
  dashboard: 'alerts',
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

export function TopLevelStudio({ viewId }: { viewId: TopLevelViewId }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const welcomeQuery = useQuery({ queryKey: ['welcome'], queryFn: api.getWelcome })
  const buildQuery = useQuery({ queryKey: ['build'], queryFn: api.getBuild })
  const dashboardQuery = useQuery({ queryKey: ['dashboard'], queryFn: api.getDashboard })
  const settingsQuery = useQuery({ queryKey: ['studio-settings'], queryFn: api.getSettings })

  const title = viewId === 'welcome' ? 'Welcome' : viewId === 'build' ? 'Build' : 'Dashboard'
  const { conversation, sendMessage, isSending } = useConversation(viewId, viewId, title)

  const [panelTabs, setPanelTabs] = useState(DEFAULT_PANEL_TABS)
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
    return storedPreset === 'system_default' || storedPreset === 'custom' ? storedPreset : 'system_default'
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
  const [connectionTestResult, setConnectionTestResult] = useState<SettingsConnectionResult | null>(null)

  const tr: Translator = (en: string, zh: string) => (language === 'zh' ? zh : en)
  const resolvedTheme = theme === 'system' ? systemTheme : theme
  const projects = useMemo(() => {
    return dashboardQuery.data?.projects ?? welcomeQuery.data?.recent_projects ?? buildQuery.data?.drafts ?? []
  }, [buildQuery.data?.drafts, dashboardQuery.data?.projects, welcomeQuery.data?.recent_projects])
  const defaultProjectId = projects[0]?.id ?? 'proj_payment'

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

  useEffect(() => {
    if (!settingsOpen) setSettingsPanel(null)
  }, [settingsOpen])

  useEffect(() => {
    if (!settingsOpen || !settingsQuery.data) return
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
    if (!settingsOpen) setConnectionTestResult(null)
  }, [settingsOpen])

  useEffect(() => {
    if (settingsPanel === 'model') setConnectionTestResult(null)
  }, [customApiKey, customBaseUrl, customModelName, customProviderKind, modelPreset, settingsPanel])

  const updateSettingsMutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['studio-settings'] })
    },
  })

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

  const activeProviderStatus = settingsQuery.data?.active_provider_status
  const persistedProvider = settingsQuery.data?.model_provider ?? 'openai'
  const activeProvider = connectionTestResult?.provider ?? (modelPreset === 'custom' ? customProviderKind : persistedProvider)

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

  const providerBannerMode = connectionTestResult?.runtime_mode ?? settingsQuery.data?.runtime_mode ?? activeProviderStatus?.mode ?? 'fallback'
  const providerBannerAvailability = connectionTestResult?.ok ?? activeProviderStatus?.available ?? false
  const providerBannerMessage = connectionTestResult?.message ?? activeProviderStatus?.reason ?? tr('No provider status returned yet.', '当前尚未返回 Provider 状态。')
  const providerBannerFallback = connectionTestResult?.fallback_provider ?? activeProviderStatus?.fallback_provider ?? settingsQuery.data?.fallback_provider ?? null

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

  function buildCustomModelPayload() {
    const payload: StudioSettingsConnectionTestRequest = {
      custom_provider_kind: customProviderKind,
      custom_base_url: customBaseUrl,
      custom_model_name: customModelName,
      model_preset: 'custom',
    }
    if (customApiKey.trim()) payload.custom_api_key = customApiKey.trim()
    return payload
  }

  function buildConnectionTestPayload(): StudioSettingsConnectionTestRequest {
    if (modelPreset === 'custom') return buildCustomModelPayload()
    return { model_preset: 'system_default' }
  }

  async function saveSystemModelConfig() {
    const updated = await updateSettingsMutation.mutateAsync({ model_preset: 'system_default' })
    setModelPreset(updated.model_preset)
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
    setConnectionTestResult(null)
  }

  async function testModelConnection() {
    await testConnectionMutation.mutateAsync(buildConnectionTestPayload())
  }

  const serverConversationMessages = useMemo<UIMessage[]>(() => {
    if (!conversation) return []
    const messageItems = conversation.messages.map((item) => {
      const html = item.blocks.map((block) => `<p style="margin:0 0 8px;">${block.text}</p>`).join('')
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
          <div class="surface-list" style="margin-top:12px;">
            ${goal.steps.map((step) => surfaceRow(step.title, tr(`Step status: ${step.status}`, `步骤状态：${step.status}`), [miniChip(step.status, statusTone(step.status))])).join('')}
          </div>
        </div>
      `,
    }))

    return [...messageItems, ...goalItems]
  }, [conversation, language])

  function seedConversation(seedView: TopLevelViewId): UIMessage[] {
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
                    ${summaryStat(tr('Versions', '版本数'), `${dashboardQuery.data?.running_versions ?? 0}`, tr('Live release branches', '活跃发布分支'))}
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
    }
  }

  const currentConversation = [...seedConversation(viewId), ...serverConversationMessages]

  function panelTabLabel(label: string) {
    if (language !== 'zh') return label
    return ({
      Activity: '动态',
      Tips: '提示',
      Status: '状态',
      Projects: '项目',
      Imports: '导入',
      Health: '健康度',
      Alerts: '告警',
      Progress: '进度',
    } as Record<string, string>)[label] ?? label
  }

  const meta = topLevelViewMeta(viewId, tr)

  function renderPanelContent() {
    const views: Record<TopLevelViewId, Record<string, string>> = {
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
          ${moduleItem(tr('Web agent runtime available', 'Web Agent 运行时可用'), 'web')}
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
          ${moduleItem(tr('1 release gate requires review', '1 个放行门禁等待审阅'), 'review')}
        `,
        progress: `
          <div class="panel-section-label">${tr('Progress', '进度')}</div>
          ${projects.map((project) => moduleItem(`${project.name} · ${project.progress}%`, project.active_version)).join('')}
        `,
        activity: panelActivity(['Dashboard risk pulse refreshed', 'Governance backlog queried', 'Project health rollup updated']),
      },
    }

    return views[viewId]?.[panelTabs[viewId]] ?? ''
  }

  async function handleSend() {
    const trimmed = composerValue.trim()
    if (!trimmed || isSending) return
    setComposerValue('')
    const lower = trimmed.toLowerCase()
    if (lower.includes('build')) navigate('/build')
    if (lower.includes('dashboard')) navigate('/dashboard')
    if (lower.includes('documentation') || lower.includes('docs')) navigate('/documentation')
    await sendMessage(trimmed)
  }

  async function invokeAction(action: string, projectId?: string) {
    const targetProjectId = projectId ?? defaultProjectId
    switch (action) {
      case 'open_build':
        navigate('/build')
        return
      case 'open_dashboard':
        navigate('/dashboard')
        return
      case 'open_documentation':
        navigate('/documentation')
        return
      case 'open_project':
        navigate(`/projects/${targetProjectId}`)
        return
      case 'open_version_create':
        navigate(`/projects/${targetProjectId}/versions/create`)
        return
      case 'open_project_create':
        navigate('/build/create-project')
        return
      case 'agent_create_project':
        await sendMessage('Help me create a new project.')
        navigate('/build/create-project')
        return
      case 'dashboard_risk_query':
        await sendMessage('Which project is riskiest right now?')
        return
      case 'dashboard_blockers_query':
        await sendMessage('Show blocked releases')
        return
      case 'open_governance':
        navigate(`/projects/${targetProjectId}/governance`)
        return
      default:
        return
    }
  }

  function handleDelegatedClick(event: MouseEvent<HTMLElement>) {
    const target = event.target as HTMLElement
    const actionTarget = target.closest<HTMLElement>('[data-action]')
    if (!actionTarget) return
    void invokeAction(actionTarget.dataset.action ?? '', actionTarget.dataset.project)
  }

  function handleSettingsAction(action: 'status' | 'terms' | 'privacy' | 'feedback' | 'billing') {
    setSettingsOpen(false)
    setSettingsPanel(null)
    if (action === 'status') {
      navigate('/dashboard')
      return
    }
    if (action === 'feedback') {
      setComposerValue(tr('I want to share product feedback about the current workspace.', '我想反馈一下当前工作台的体验问题。'))
      return
    }
    navigate('/documentation')
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
              <button className={`settings-submenu-option ${theme === option.value ? 'active' : ''}`} key={option.value} type="button" onClick={() => setTheme(option.value)}>
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
              <button className={`settings-submenu-option stacked ${language === option.value ? 'active' : ''}`} key={option.value} type="button" onClick={() => setLanguage(option.value)}>
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
      const connectionResultTone = connectionTestResult ? (!connectionTestResult.ok ? 'error' : connectionTestResult.runtime_mode === 'live' ? 'success' : 'warning') : null
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
              ? tr(`Main agent route: ${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`, `主 Agent 路由：${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`)
              : tr('Select the workspace default used by the main agent for planning and generation.', '选择主 Agent 在规划与生成时默认使用的工作模型。')}
          </div>
          <div className="settings-provider-banner">
            <div className="settings-provider-status-row">
              <span className="settings-provider-pill neutral">{providerLabel(activeProvider)}</span>
              <span className={`settings-provider-pill ${providerBannerMode === 'live' ? 'live' : 'fallback'}`}>{providerBannerMode === 'live' ? tr('live', 'live') : tr('fallback', 'fallback')}</span>
              {(connectionTestResult || activeProviderStatus) ? (
                <span className={`settings-provider-pill ${providerBannerAvailability ? 'good' : 'warn'}`}>
                  {providerBannerAvailability ? tr('Provider ready', 'Provider 已就绪') : tr('Provider unavailable', 'Provider 不可用')}
                </span>
              ) : null}
            </div>
            <span className="settings-provider-copy">{providerBannerMessage}</span>
            {providerBannerFallback ? <span className="settings-runtime-copy">{tr(`Fallback provider: ${providerBannerFallback}`, `回退 Provider：${providerBannerFallback}`)}</span> : null}
          </div>
          <div className="settings-submenu-list">
            {modelOptions.map((option) => (
              <button className={`settings-submenu-option stacked ${modelPreset === option.value ? 'active' : ''}`} key={option.value} type="button" onClick={() => setModelPreset(option.value)}>
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
              <div className="settings-form-copy">{tr('Use this when you want Nasus to call an OpenAI-compatible endpoint or your own provider route.', '当你希望 Nasus 调用 OpenAI 兼容接口或你自己的 Provider 路由时使用。')}</div>
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
                <input className="settings-field-control" type="text" placeholder="https://api.example.com/v1" value={customBaseUrl} onChange={(event) => setCustomBaseUrl(event.target.value)} />
              </label>
              <label className="settings-field">
                <span className="settings-field-label">{tr('Model name', '模型名称')}</span>
                <input className="settings-field-control" type="text" placeholder="your-model-name" value={customModelName} onChange={(event) => setCustomModelName(event.target.value)} />
              </label>
              <label className="settings-field">
                <span className="settings-field-label">API Key</span>
                <input className="settings-field-control" type="password" placeholder={customHasApiKey && customMaskedKey ? `${tr('Saved', '已保存')} ${customMaskedKey}` : tr('Paste API key', '粘贴 API Key')} value={customApiKey} onChange={(event) => setCustomApiKey(event.target.value)} />
              </label>
              <div className="settings-form-meta">
                {customHasApiKey && customMaskedKey ? tr(`Saved key: ${customMaskedKey}`, `已保存密钥：${customMaskedKey}`) : tr('No custom API key saved yet.', '尚未保存自定义 API Key。')}
              </div>
              <div className="settings-form-meta">
                {tr('Base URL, provider type, and model name are kept as a local draft across refresh. API keys are only persisted after Save custom model.', 'Base URL、Provider 类型和模型名会在刷新后保留为本地草稿；API Key 只有点击“保存自定义模型”后才会持久化。')}
              </div>
              <div className="settings-form-actions">
                <button className="settings-save-button secondary" type="button" disabled={testConnectionMutation.isPending} onClick={() => void testModelConnection()}>
                  {testConnectionMutation.isPending ? tr('Testing...', '测试中...') : tr('Test connection', '测试连接')}
                </button>
                <button className="settings-save-button" type="button" disabled={updateSettingsMutation.isPending} onClick={() => void saveCustomModelConfig()}>
                  {tr('Save custom model', '保存自定义模型')}
                </button>
              </div>
            </div>
          ) : (
            <div className="settings-form-block">
              <div className="settings-form-title">{tr('System-managed route', '系统托管路由')}</div>
              <div className="settings-form-copy">{tr('Nasus will use the backend-managed default provider route. You can test the current route status without opening the custom provider form.', 'Nasus 会使用后端托管的默认 Provider 路由。你可以直接测试当前路由状态，无需展开自定义配置。')}</div>
              <div className="settings-form-meta">
                {settingsQuery.data ? tr(`Current route: ${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`, `当前路由：${providerLabel(settingsQuery.data.model_provider)} / ${settingsQuery.data.model_name}`) : tr('Settings are loading from the server.', '正在从服务端加载设置。')}
              </div>
              <div className="settings-form-actions">
                <button className="settings-save-button secondary" type="button" disabled={testConnectionMutation.isPending} onClick={() => void testModelConnection()}>
                  {testConnectionMutation.isPending ? tr('Testing...', '测试中...') : tr('Test connection', '测试连接')}
                </button>
                <button className="settings-save-button" type="button" disabled={updateSettingsMutation.isPending} onClick={() => void saveSystemModelConfig()}>
                  {tr('Use default system model', '使用默认系统模型')}
                </button>
              </div>
            </div>
          )}
          {connectionTestResult ? (
            <div className={`settings-test-result ${connectionResultTone ?? 'warning'}`}>
              <div className="settings-test-result-header">
                <span className="settings-test-result-title">
                  {!connectionTestResult.ok ? tr('Connection unavailable', '连接不可用') : connectionTestResult.runtime_mode === 'live' ? tr('Connection healthy', '连接成功') : tr('Fallback active', '已进入回退')}
                </span>
              </div>
              <div className="settings-test-result-copy">
                {providerLabel(connectionTestResult.provider)} / {connectionTestResult.model_name} · {connectionTestResult.runtime_mode === 'live' ? tr('live', 'live') : tr('fallback', 'fallback')}
              </div>
              {typeof connectionTestResult.latency_ms === 'number' ? <div className="settings-test-result-time">{tr(`Latency ${connectionTestResult.latency_ms} ms`, `延迟 ${connectionTestResult.latency_ms} ms`)}</div> : null}
              {connectionTestResult.fallback_provider ? <div className="settings-test-result-time">{tr(`Fallback provider ${connectionTestResult.fallback_provider}`, `回退 Provider ${connectionTestResult.fallback_provider}`)}</div> : null}
              <div className="settings-test-result-copy">{connectionTestResult.message}</div>
            </div>
          ) : null}
        </div>
      )
    }

    if (settingsPanel === 'notifications') {
      const notificationOptions: { value: NotificationMode; label: string; detail: string }[] = [
        { value: 'important', label: tr('Important only', '仅重要通知'), detail: tr('Approvals, conflicts, and failed runs', '审批、冲突和失败执行') },
        { value: 'all', label: tr('All updates', '全部更新'), detail: tr('Include progress, summaries, and activity signals', '包含进度、总结和活动信号') },
        { value: 'muted', label: tr('Mute', '静默'), detail: tr('Keep alerts inside the activity panel only', '仅在活动面板内保留提醒') },
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
              <button className={`settings-submenu-option stacked ${notificationMode === option.value ? 'active' : ''}`} key={option.value} type="button" onClick={() => setNotificationMode(option.value)}>
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

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%' }} onClick={handleDelegatedClick}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo" id="home-link" style={{ cursor: 'pointer' }} onClick={() => navigate('/welcome')}>
            Nasus Studio
            <span className="sidebar-version">v</span>
          </div>
        </div>
        <nav className="sidebar-nav custom-scrollbar">
          <div className="sidebar-section-label" style={{ paddingTop: 8 }}>{tr('Studio', '工作室')}</div>
          <button className={`sidebar-nav-item ${viewId === 'welcome' ? 'active' : ''}`} onClick={() => navigate('/welcome')}>
            <i className="fa-solid fa-house" />
            {tr('Welcome', '欢迎')}
          </button>
          <div className="sidebar-section-label">{tr('Explore', '探索')}</div>
          {[
            ['build', 'fa-solid fa-hammer', tr('Build', '创建项目')],
            ['dashboard', 'fa-solid fa-chart-line', tr('Dashboard', '全局仪表盘')],
            ['documentation', 'fa-solid fa-book-open', tr('Documentation', '产品文档')],
          ].map(([id, icon, label]) => (
            <button className={`sidebar-nav-item ${viewId === id ? 'active' : ''}`} key={id} onClick={() => navigate(`/${id}`)}>
              <i className={icon} />
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button className="sidebar-footer-link"><i className="fa-regular fa-lightbulb" />{tr("What's new", '最新内容')}</button>
          <button className="sidebar-footer-link"><i className="fa-solid fa-key" />{tr('Get API key', '获取 API Key')}</button>
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
              <Fragment key={`${viewId}:${index}`}>{renderPrototypeMessage(item)}</Fragment>
            ))}
            {isSending ? (
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
                  </div>
                  <button className="send-btn" type="button" disabled={!composerValue.trim() || isSending} onClick={() => void handleSend()}>
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
            {PANEL_TABS[viewId].map((tab) => (
              <button className={`panel-tab ${panelTabs[viewId] === tab.id ? 'active' : ''}`} key={tab.id} type="button" onClick={() => setPanelTabs((current) => ({ ...current, [viewId]: tab.id }))}>
                {panelTabLabel(tab.label)}
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
                <button className={`settings-menu-item ${settingsPanel === 'model' ? 'active' : ''}`} type="button" onClick={() => setSettingsPanel((current) => (current === 'model' ? null : 'model'))}>
                  <span className="settings-menu-icon"><i className="fa-solid fa-circle-nodes" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Model configuration', '模型配置')}</span>
                    <span className="settings-menu-detail">
                      {settingsQuery.data ? `${providerLabel(persistedProvider)} · ${settingsQuery.data.model_name}` : tr('Loading model settings', '加载模型设置中')}
                    </span>
                  </span>
                  <span className="settings-menu-chevron"><i className="fa-solid fa-chevron-right" /></span>
                </button>
                <button className={`settings-menu-item ${settingsPanel === 'theme' ? 'active' : ''}`} type="button" onClick={() => setSettingsPanel((current) => (current === 'theme' ? null : 'theme'))}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-sun" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Theme', '主题')}</span>
                    <span className="settings-menu-detail">{tr('Dark, light, or follow system.', '深色、浅色或跟随系统。')}</span>
                  </span>
                  <span className="settings-menu-chevron"><i className="fa-solid fa-chevron-right" /></span>
                </button>
                <button className={`settings-menu-item ${settingsPanel === 'language' ? 'active' : ''}`} type="button" onClick={() => setSettingsPanel((current) => (current === 'language' ? null : 'language'))}>
                  <span className="settings-menu-icon"><i className="fa-solid fa-language" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Language', '语言')}</span>
                    <span className="settings-menu-detail">{language === 'zh' ? '中文' : 'English'}</span>
                  </span>
                  <span className="settings-menu-chevron"><i className="fa-solid fa-chevron-right" /></span>
                </button>
                <button className={`settings-menu-item ${settingsPanel === 'notifications' ? 'active' : ''}`} type="button" onClick={() => setSettingsPanel((current) => (current === 'notifications' ? null : 'notifications'))}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-bell" /></span>
                  <span className="settings-menu-copy">
                    <span className="settings-menu-title">{tr('Applet notifications', '工作台通知')}</span>
                    <span className="settings-menu-detail">{notificationMode === 'all' ? tr('All updates', '全部更新') : notificationMode === 'muted' ? tr('Muted', '静默') : tr('Important only', '仅重要通知')}</span>
                  </span>
                  <span className="settings-menu-chevron"><i className="fa-solid fa-chevron-right" /></span>
                </button>
                <div className="settings-menu-divider" />
                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('status')}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-eye" /></span>
                  <span className="settings-menu-copy"><span className="settings-menu-title">{tr('View status', '查看状态')}</span></span>
                </button>
                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('terms')}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-file-lines" /></span>
                  <span className="settings-menu-copy"><span className="settings-menu-title">{tr('Terms of service', '服务条款')}</span></span>
                </button>
                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('privacy')}>
                  <span className="settings-menu-icon"><i className="fa-solid fa-shield-heart" /></span>
                  <span className="settings-menu-copy"><span className="settings-menu-title">{tr('Privacy policy', '隐私政策')}</span></span>
                </button>
                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('feedback')}>
                  <span className="settings-menu-icon"><i className="fa-regular fa-flag" /></span>
                  <span className="settings-menu-copy"><span className="settings-menu-title">{tr('Send feedback', '发送反馈')}</span></span>
                </button>
                <button className="settings-menu-item utility" type="button" onClick={() => handleSettingsAction('billing')}>
                  <span className="settings-menu-icon"><i className="fa-solid fa-flask" /></span>
                  <span className="settings-menu-copy"><span className="settings-menu-title">{tr('Billing Support', '计费支持')}</span></span>
                </button>
              </div>
            </div>
            {settingsPanel ? <div className="settings-subpanel-shell">{renderSettingsSubmenu()}</div> : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
