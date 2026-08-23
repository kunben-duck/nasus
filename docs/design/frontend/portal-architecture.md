# Nasus Portal 前端架构

## 1. 文档定位

本文合并原“前端应用架构”和“前端页面蓝图”，统一定义：

- Portal 的工程目录、路由、状态分层和测试策略
- `ux/` 原型对应的 16 个视图、页面层级树、右栏映射与组件目录
- Agent Goal UI、页面级模块蓝图和导航下钻规则

优先级关系：

- 视觉与交互基线以 [./visual-style.md](./visual-style.md) 和 `ux/` 原型为准。
- 业务对象与接口以 [实现总览](../../implementation-overview.md) 为准。

## 2. 应用边界

当前阶段前端聚焦一个应用：

- `apps/portal`

共享包：

- `packages/ui`
- `packages/tokens`
- `packages/api-client`
- `packages/contracts`
- `packages/state`

## 3. 工程目录建议

```text
apps/portal/src/
  app/
    router.tsx
    providers.tsx
    shells/
      TopLevelStudioShell.tsx
      ProjectWorkspaceShell.tsx
  routes/
    build/
    dashboard/
    documentation/
    project-overview/
    version-space/
    workspace/
    knowledge/
    runs/
    governance/
    release-readiness/
  domains/
    system-image/
    agent/
    quality-loop/
    platform/
  shared/
    api/
    ui/
    tokens/
    event-reducer/
```

迁移准入：

- `app/providers.tsx` 统一组装 QueryClient、全局 store、主题、语言、错误边界和通知宿主。
- `app/router.tsx` 只能挂载 route page，不得把所有 canonical route 统一指向单体原型组件。
- `routes/*` 是页面入口，负责 shell slot、页面级加载/空态/错误态和 route params 解析。
- `domains/*` 提供对应产品域的 view model、query key、mutation 和事件 reducer 适配。
- `shared/ui` 沉淀 AI Studio 风格 primitive：composer、settings popover、icon button、skill chip、project card、status badge。
- `shared/ui` 只沉淀产品无关 primitive。Nasus 顶层侧栏、项目空间导航、设置锚点和账户 chrome 属于 `app/shells`，不能放入 shared。
- `shared/tokens` 是唯一视觉 token 来源，所有线性图标遵循 AI Studio 轻线条风格：约 `1.5px` stroke、圆角端点、16-18px 视觉盒、不可被压扁或拉伸。
- 生产 Portal 的字体和图标字体必须随应用自托管并保留上游许可证，不允许把 Google Fonts、Material Symbols 或 Font Awesome CDN 作为首屏加载依赖；网络隔离或第三方 CDN 抖动不得阻塞 route `load` 与 E2E。
- `NasusStudio`、`PrototypeStudio`、`TopLevelStudio` 仅作为迁移期视觉参考，不允许新增业务逻辑。
- 登录 token 的浏览器持久化属于 `domains/platform/authTokenStorage.ts`。
  `shared/api/client.ts` 只能通过可配置 token provider 附加 auth header，
  不得直接读写 `localStorage` 或持有具体 storage key。

写动作边界：

- route 层只负责 UI 锁、导航、参数解析和 query invalidation。
- 项目空间按钮、卡片和 chip 触发的写动作必须进入 `domains/platform/tool-actions/projectActionExecutor.ts`、`domains/platform/toolInvocationCommands.ts` 或对应 Agent command module。
- 路由目录不得新增薄代理 action executor 文件；route action handler 应直接 import 领域命令模块，保持写动作命令面只有一个 canonical owner。
- 项目空间 query invalidation 规则必须进入 `domains/platform/projectWorkspaceInvalidation.ts`，route 只能调用该 domain helper，不得新增 `projectRouteInvalidation.ts` 这类 route-local 刷新策略。
- ToolInvocation 确认必须通过 `domains/platform/useToolInvocationConfirmation.ts`，route 不得直接持有 `useMutation` 或调用 `platformApi.confirmToolInvocation`。
- 项目空间聚合读模型必须进入 `domains/platform/useProjectWorkspaceData.ts`，由该 hook 组合 Quality Loop 与 System Image 读 API；route 模块只传入 URL 参数和处理导航，不直接 import `qualityLoopApi` 或 `systemImageApi`。
- route 层不得直接调用 `platformApi.invokeTool`、`platformApi.confirmToolInvocation`、`agentApi.postMessage` 或 `agentApi.resumeAgentGoal`。
- 如果新增按钮不能映射到 Agent 可调用的 tool/conversation command，则不得进入页面实现。

## 4. Canonical 页面层级树

```text
L0 Root
  - Welcome

L1 Product Areas
  - Build
  - Dashboard
  - Documentation

L2 Project Space
  - Project Overview
  - Version Space
  - Version Create
  - Personal Workspace
  - Knowledge Gallery
  - Knowledge Detail
  - Runs
  - Run Detail
  - Governance
  - Approval Detail
  - Release Readiness
```

规则：

- `Build` 是项目创建和初始化入口
- `Dashboard` 是项目组合视图
- 点击项目卡后进入独立 `Project Space`
- `Personal Workspace` 是单个 US 的核心质量闭环工作台

## 5. 路由结构

### 5.1 Portal

- `/`
- `/welcome`
- `/build`
- `/dashboard`
- `/documentation`
- `/projects/:projectId`
- `/projects/:projectId/versions`
- `/projects/:projectId/versions/new`
- `/projects/:projectId/workspaces/:usId`
- `/projects/:projectId/knowledge`
- `/projects/:projectId/knowledge/:objectId`
- `/projects/:projectId/runs`
- `/projects/:projectId/runs/:runId`
- `/projects/:projectId/governance`
- `/projects/:projectId/approvals/:approvalId`
- `/projects/:projectId/release-readiness`
- `/conversations`
- `/agent-goals/:goalId?`

### 5.2 生产入口准入

正式入口必须采用：

`App -> RouterProvider -> route module -> page component -> shell`

准入规则：

- `App.tsx` 不得直接渲染单体原型组件。
- canonical route 必须全部指向真实页面组件。
- `PrototypeStudio`、`TopLevelStudio` 或其他原型组件只能作为设计参考，不得作为生产路由实现。
- 每个 route module 必须声明 `page_id`、`shell`、`required_query_keys`、`right_panel_config`、`loading_state`、`empty_state` 和 `error_boundary`。
- 深链刷新后必须能恢复当前项目、版本、US、Run、Approval 或 AgentGoal 视图。

## 6. 导航与下钻规则

### 6.1 顶层导航

- 顶层导航采用 AI Studio Apps 风格的分组侧栏，而不是普通后台菜单。
- 分组固定为：
  - `EXPLORE`：`Welcome`、`Recent Sessions`
  - `BUILD`：`New Project`、`My Projects`
  - `MANAGE`：`Dashboard`、`Documentation`
- `Build` 对应 `New Project` 选中态，点击后进入项目创建与初始化画布。
- `Build` 会话负责：创建项目、导入 Git/US/UX、初始化系统画像
- `Dashboard` 会话负责：全局项目进展、风险、阻塞项和审批积压
- 侧栏底部固定显示：状态卡、通知、设置、搜索/API key 或模型配置入口、账户 chip。
- 桌面端顶层导航必须支持展开/收起。展开态显示品牌、分组、label、状态卡和底部账号；收起态保留图标、当前态、tooltip 和底部工具入口。
- 收起态是同一套导航结构的 compact rail，不是新的移动端菜单，也不能改变当前路由或重新挂载页面。

### 6.2 项目空间导航

进入项目空间后，左侧导航整体替换为：

- `Project Overview`
- `Version Space`
- `Personal Workspace`
- `Knowledge`
- `Runs`
- `Governance`

详情态页面不单列一级入口，但必须保留父导航高亮与稳定返回。

### 6.3 顶层壳层与项目壳层切换

- `Welcome / Build / Dashboard / Documentation` 使用 `TopLevelStudioShell`：
  - 左侧分组导航
  - 中间居中大画布
  - 右上浮动设置按钮
  - 无默认常驻右栏
- 进入 `/projects/:projectId` 后使用 `ProjectWorkspaceShell`：
  - 左侧导航整体替换为项目内菜单
  - 中间内容工作区
  - 右侧 inspector / context rail 常驻或可折叠
- 顶层壳层和项目壳层不能同时渲染左侧二级菜单；下钻必须是整栏替换。
- 壳层必须拆分为 container 与 view：`TopLevelStudioShell` /
  `ProjectWorkspaceShell` 可以组合 settings/account 的 platform hooks，
  但 `*ShellView.tsx` 只能处理布局 chrome、折叠状态、settings popover
  锚点和 slots，不能 import `domains/*` 或执行业务 workflow。
- 顶层侧栏这类产品 chrome 放在 `app/shells`。导航副作用由 shell
  container 使用 router hook 处理，再以 `onNavigate` callback 注入 view；
  shared UI 不得 import `react-router-dom`、持有具体路由 path 或渲染
  Nasus 产品导航。
- 前端依赖方向必须由 `tests/test_portal_boundaries.py` 的 import-boundary
  gate 自动校验：`shared` 不得 import `app/routes/domains`；`domains`
  不得 import `app/routes` 或 `shared/ui`；`*ShellView.tsx` 不得 import
  domain 代码；route modules 不得绕过 domain command surface 直接调用 raw
  API 写动作。

### 6.4 设置菜单与顶层对话样式

- `TopLevelStudioShell` 必须提供 `navCollapsed` UI state，并持久化到 local UI store；主画布根据导航宽度自然重排。
- `Settings` 入口由左侧底部工具按钮和右上浮动按钮共同触发同一个 overlay popover，不能打开两套不同设置 UI。
- 设置 popover 必须支持点击式二级菜单：一级菜单只展示 `Theme`、`Language`、`Model configuration`、`Notifications`、`Provider status` 等入口，点击某一项后在右侧展开对应选项。不得把所有配置直接平铺在同一个设置页里。
- 二级菜单向右展开，空间不足时原位替换并显示返回行。
- `Model configuration` 必须提供 `LLM / Embedding / Rerank` 三个 route tab。每个 route 独立展示 `system_default/custom`、provider、base URL、model、API key、live/fallback 状态、`Test connection` 和保存动作。
- `LLM` route 驱动主会话、Conversation Orchestrator 与 Agent Loop；`Embedding` route 驱动系统画像向量化；`Rerank` route 驱动 hybrid retrieval 候选重排。前端不得把三者合并成同一个表单状态。
- 设置 popover 不得影响页面布局，不得导致主配置框整体上浮；长内容只允许弹层内部滚动。
- `Build` 首页的 composer 是顶层主交互组件，必须居中对齐 Hero 标题，宽度与能力 chip row 对齐。
- `Build` 首页主按钮规则：`I guess you` 用于推荐技能并生成提示词；`Build` 仅在输入框已有提示词或技能选择有效后显示并发起工具调用。
- `Build` 首屏的 discover/project 模块只作为下半屏辅助内容，不能用大卡片抢占主页对话框的首屏焦点。

## 7. 状态管理分层

### 7.1 Server State

由 TanStack Query 管理：

- `ConversationSession`
- `Conversation`
- `AgentGoal`
- `ToolInvocation`
- `Task`
- `Run`
- `Approval`
- `ConnectorRun`
- `MCPServerHealth`

### 7.2 Event State

由统一 `EventReducer` 管理，消费 SSE 事件流：

- patch
- append
- invalidate
- version check
- `conversation.message.created` 必须优先用 `payload.message` append 到 `ConversationSession.messages`
- `agent.goal.updated` 必须优先用 `payload.agent_goal` upsert 到 `ConversationSession.agent_goals`
- 只有 `snapshot_hint=true`、`mutation_kind=invalidate` 或 payload 不可合并时，才对 `["conversation", conversationId]` 做精确 refetch

### 7.3 UI State

由 Zustand 或等价 store 管理：

- `activeNav`
- `navCollapsed`
- `activeContextTab`
- `composerState`
- `selectedRunId`
- `selectedObjectId`
- `settingsPopover`
- `settingsSubmenu`
- `activeModelRoute`

### 7.4 Streaming State

由 `MessageStreamAssembler` 负责：

- `streamId`
- `messageId`
- `sequence`
- `draftContent`
- `structuredBlocks`
- `toolProgressMap`
- `streamStatus=idle|streaming|interrupted|completed`

### 7.5 Action Registry

所有 UI 写动作必须通过前端 Action Registry 进入同一工具调用链。

当前首批实现位置：

- `apps/portal/src/domains/platform/tool-actions/`
- `apps/portal/src/domains/platform/toolInvocationCommands.ts`
- `Build / Project Workspace` 中的系统画像、质量闭环、Release gate、系统画像状态查询等按钮和 chip 都必须通过该 registry 生成 `conversation_message` 或 `tool_invocation` command。
- registry 允许少数高层目标先进入 `POST /v1/conversations/{id}/messages`，例如 `system-image.build-goal` 与 `quality-loop.continue-goal`，但这些会话目标后续仍必须由 Orchestrator / AgentGoal 生成正式 `ToolInvocation`。

首批 action id：

- `system-image.build-goal`
- `system-image.register-sources`
- `system-image.ingest-sources`
- `system-image.materialize-context`
- `system-image.initialize-baseline`
- `system-image.status`
- `quality-loop.continue-goal`
- `release.assess`

Action 定义至少包含：

- `action_id`
- `label`
- `surface=button|chip|card|composer|menu`
- `target_tool_id`
- `payload_builder`
- `required_context`
- `confirmation_hint`
- `disabled_reason`
- `optimistic_update_mode=none|local_pending`
- `result_query_keys`

执行规则：

- button、chip、card action 不得直接调用领域写接口。
- composer 可以先调用 `POST /v1/conversations/{id}/messages`，但 Orchestrator 输出写计划后仍必须创建 `ToolInvocation`。
- 高风险 action 必须显示 gate 状态和阻断原因。
- action pending 期间必须锁定互斥动作，并在 `tool.invocation.updated` 后恢复。
- US 文档和测试资产的浏览器上传通过 `domains/system-image/sourceUploadCommands.ts` 进入托管对象存储，只返回 source URI；页面不得把上传成功解释为领域 source 已注册。注册、摄入、物化和基线初始化仍由上述 Action Registry / ToolInvocation 链路执行。

### 7.6 SSE Reducer 矩阵

| event_type | 合并策略 |
| --- | --- |
| `conversation.message.created` | append message |
| `assistant.message.delta` | MessageStreamAssembler append delta |
| `assistant.message.completed` | finalize streaming message |
| `agent.goal.updated` | upsert AgentGoal |
| `agent.step.updated` | upsert AgentStep |
| `agent.step.thinking.delta` | append ThinkingCard delta |
| `tool.invocation.updated` | upsert ToolInvocationTimeline item |
| `agent.swarm.updated` | upsert SwarmRunPanel |
| `task.updated` | patch Task / TaskContext |
| `run.updated` | patch Run / Evidence summary |
| `approval.updated` | patch Approval / Gate card |

Reducer 规则：

- 基于 `event_id` 去重。
- 基于 `entity_version` 丢弃旧事件。
- 只有 payload 不可合并、`snapshot_hint=true` 或 `mutation_kind=invalidate` 时才精确 refetch。
- 不得把 SSE 退化成全量刷新提示。

## 8. 页面级蓝图

### 8.1 Welcome

- 中栏：AI Studio 式 Hero、最近项目 shortcut、Recent Conversations、能力 chip row、`TopLevelComposer`
- 浮动设置：打开 `Activity / Tips / Status` overlay rail

### 8.2 Build

- 中栏首屏固定为：
  - Hero：`Build your quality workspace with Nasus`
  - `Project Creation Composer`：大输入卡，placeholder 为“Describe your project, paste a Git URL, or ask Agent to guide setup”
  - 左下工具按钮：语音/附件/引用上下文
  - 右侧主按钮：`Guide me` / `Initialize with agent`
  - 横向 chip row：`Import Git`、`Import US doc`、`Import UX`、`Import OpenAPI`、`Initialize system image`、`Create from template`
  - 下半屏：`Draft Projects`、`Project Templates`、`Recent Imports`
- 浮动设置：打开 `Projects / Imports / Health` overlay rail

### 8.3 Dashboard

- 中栏：组合态 Hero Query Composer、项目卡片网格、风险/阻塞摘要、快捷问询 chips、全局进展卡
- 浮动设置：打开 `Alerts / Progress / Activity` overlay rail

### 8.4 Documentation

- 中栏：Documentation Hero、搜索 composer、分类卡、Templates、Examples、方法论推荐 chips
- 浮动设置：打开 `Topics / Templates / Updates` overlay rail

### 8.5 Project Overview

- 中栏：项目摘要、Official System Image、Connected Sources、Active Versions、Risk Signals、项目级会话区
- 右栏：`Context / Assets / Activity`

### 8.6 Version Space

- 中栏：版本头部、US Board、版本风险摘要、Pending Execution、Pending Approval、会话区
- 右栏：`Board / Risk / Activity`

### 8.7 Version Create

- 中栏：Version Basics、Source Branch、US Import、Owner Assignment、Baseline Fork Preview、会话区
- 右栏：`Summary / Owners / Fork`

### 8.8 Personal Workspace

- 中栏采用 AI Studio Agents 式任务工作台：
  - 顶部：US / Task breadcrumb、页面标题、`Tasks / Agents` segmented control、更多操作按钮
  - 模板区：`TaskTemplateGrid`，展示 `Impact Analyst`、`Scenario Designer`、`Case Generator`、`Automation Runner`、`Failure Analyst`、`Release Advisor`
  - 运行区：当前 `AgentGoalCard`、`AgentStepRail`、`SwarmRunPanel`、`ToolInvocationTimeline`
  - 资产区：`Quality Asset Pack`、`ChatTimeline`、结构化结果卡
  - 底部：固定 `ActionComposer`，内含工具 chips、附件入口、运行按钮
- 右栏采用 `Run Settings` 风格：`Profile / Tools / Environment / Evidence / Policy`

### 8.9 Knowledge Gallery / Detail

- Gallery 右栏：`Graph / Objects / Search`
- Detail 右栏：`Context / Evidence / Activity`

### 8.10 Runs / Run Detail

- Runs 右栏：`Active / History / Failed`
- Run Detail 右栏：`Evidence / Failure / Activity`

### 8.11 Governance / Approval Detail / Release Readiness

- Governance 右栏：`Pending / Resolved / Policy`
- Approval Detail 右栏：`Diff / Evidence / History`
- Release Readiness 右栏：`Blockers / Signals / Activity`

## 9. 右栏面板映射表

| 页面 | 右栏标题 | Tabs |
| --- | --- | --- |
| Welcome | Studio Overview overlay | `Activity` `Tips` `Status` |
| Build | Build Context overlay | `Projects` `Imports` `Health` |
| Dashboard | Global Signals overlay | `Alerts` `Progress` `Activity` |
| Documentation | Docs Navigator overlay | `Topics` `Templates` `Updates` |
| Project Overview | Project | `Context` `Assets` `Activity` |
| Version Space | Version | `Board` `Risk` `Activity` |
| Version Create | Version Draft | `Summary` `Owners` `Fork` |
| Personal Workspace | Run settings | `Profile` `Tools` `Environment` `Evidence` `Policy` |
| Knowledge Gallery | Knowledge | `Graph` `Objects` `Search` |
| Knowledge Detail | Object Detail | `Context` `Evidence` `Activity` |
| Runs | Runs | `Active` `History` `Failed` |
| Run Detail | Run Detail | `Evidence` `Failure` `Activity` |
| Governance | Governance | `Pending` `Resolved` `Policy` |
| Approval Detail | Approval | `Diff` `Evidence` `History` |
| Release Readiness | Release Gate | `Blockers` `Signals` `Activity` |

## 10. 功能模块

- `welcome`
- `build`
- `dashboard`
- `documentation`
- `project-overview`
- `version-space`
- `version-create`
- `personal-workspace`
- `knowledge`
- `knowledge-detail`
- `runs`
- `run-detail`
- `governance`
- `approval-detail`
- `release-readiness`
- `conversation`
- `conversation-management`
- `agent-goals`
- `tools`
- `approvals`
- `settings`
- `connectors`
- `mcp-servers`

每个 feature 至少包含：

- `api.ts`
- `queries.ts`
- `reducer.ts`
- `components/`
- `types.ts`

## 11. 组件边界

### 11.1 共享壳层组件

- `WorkspaceShell`
- `TopLevelStudioShell`
- `ProjectWorkspaceShell`
- `GlobalNav`
- `NavCollapseButton`
- `WorkspaceNav`
- `TopContextBar`
- `PageHeader`
- `RightPanelTabs`
- `ActionComposer`
- `TopLevelComposer`
- `CapabilityChipRow`
- `FloatingSettingsButton`
- `SettingsPopover`
- `SettingsSubmenu`
- `ActivityInbox`

### 11.2 会话与 Agent 组件

- `ChatTimeline`
- `StructuredMessageCard`
- `AgentGoalCard`
- `AgentStepRail`
- `ThinkingCard`
- `MemoryContextPanel`
- `SwarmRunPanel`
- `SuggestionChip`
- `GhostChip`

### 11.3 业务组件

- `ProjectCard`
- `VersionCard`
- `USBoard`
- `USCard`
- `RunCard`
- `ApprovalCard`
- `ReleaseReadinessPanel`
- `FailureTimelineCard`
- `EvidenceCard`
- `DiffViewer`
- `ProgressRing`
- `ToolPalette`
- `ToolInvocationTimeline`
- `ConflictPanel`
- `EvidenceTimeline`
- `GovernancePanel`
- `TaskTemplateGrid`
- `TaskTemplateCard`
- `RunSettingsPanel`
- `ComposerToolChip`

## 12. Agent Service UI 规格

`Agent Service` 至少包含：

- `Goal Header`
- `Goal Step Rail`
- `Thinking Card`
- `Tool Action Card`
- `Memory Context Panel`
- `Swarm Run Panel`
- `Interrupt Controls`

要求：

- 支持 `draft|running|paused|blocked|completed|failed|cancelled`
- 支持 `Pause / Resume / Cancel / Give Feedback`
- `thinking` 和 `observing` 采用折叠卡，不直接塞长文本
- `waiting_confirmation`、`waiting_approval`、`pending_merge` 显示为显式 blocker 卡
- `ToolInvocationTimeline` 必须通过 `GET /v1/tool-invocations?conversation_id=...` 或 `?agent_goal_id=...` 获取事实链路，不能从消息文本或 `AgentStep` 嵌套字段临时推断工具执行历史
- `MemoryContextPanel` 必须通过 `GET /v1/agent-memory/context?conversation_id=...` 或 `?agent_goal_id=...` 获取可解释摘要，只展示 `context_hash / context_summary / working_memory / conversation_memory / project_long_term_memory / candidate_memory / tool_catalog`，不得要求后端返回完整 prompt dump

## 13. 错误、通知与测试

- 错误展示分层：`field / action / panel / banner / modal / fatal`
- 通知采用 `toast + activity inbox`
- 测试至少覆盖：
  - 单元测试
  - 组件测试
  - 集成测试
  - E2E

## 14. 实现默认值

- 所有公开页面必须与 `ux/` 高保真原型的风格、布局和交互一致
- 页面不可见差异不得通过“先上简化版”绕过
- 新页面替换正式入口前，必须完成与 `ux/` 的逐页对照
