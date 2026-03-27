# 前后端方案设计

本文以 [nasus_assurance_studio_implementation_plan.md](/Users/uben/project/project/Nasus/nasus_assurance_studio_implementation_plan.md) 为主依据；其中技术栈和系统分层来自计划书原文，接口边界、运行单元拆分和阶段性落地建议属于基于计划书的工程化展开。

文档优先级说明：

- 本文用于定义当前推荐的工程实现方案和模块边界。
- 若本文与 [docs/final-feature-spec.md](/Users/uben/project/project/Nasus/docs/final-feature-spec.md) 存在冲突，以最终特性说明书定义的产品能力和默认规则为准。
- 尤其在 Agent 能力边界上，本文保留当前工程视角下的实现建议；最终产品能力以“Agent 可原生触发检索与执行，但必须经过策略、审计与回放约束”为准。
- 更细的前端目录结构、路由、状态管理分层、构建部署与测试策略以 [docs/frontend-application-architecture.md](/Users/uben/project/project/Nasus/docs/frontend-application-architecture.md) 为准。
- 页面层级树、页面级模块蓝图、右栏面板映射和 Agent Goal UI 组件规范以 [docs/frontend-page-blueprints.md](/Users/uben/project/project/Nasus/docs/frontend-page-blueprints.md) 为准。

## 1 目标与范围
- 目标：把《实施计划书》中定义的“质量保障与上线防护工作台”做实成一套前后台协作明确、角色职责清晰、执行可落地的实施方案。
- 范围：涵盖集中式 Web Portal、个人 Desktop Client、后端编排/领域服务、执行层 runner、存储/索引/解析底座以及它们之间的接口。确保 Web 前端聚焦“任务与审阅”“上下文可追踪”“组织级协作”，Desktop Client 聚焦“本地权限执行”“本地产物产出”“个人环境上下文感知”，后端聚焦“上下文产出+决策闭环”，执行层负责确定性资产运行，底层存储支持对象/原料/证据。

## 2 技术栈选型与理由
- **中心后端**：`Python + FastAPI + durable workflow（默认 Temporal） + LangGraph`。FastAPI 提供会话入口、工具调用入口、对象查询和 SSE 事件输出；durable workflow 负责长生命周期任务、审批等待、重试和恢复；LangGraph 负责单任务内部的 Agent 图编排、Tool 选择后的 Skill 路由、Worker 并行与人机节点。
- **Web 前端**：`React + TypeScript + Tailwind + Zustand/Redux Toolkit + TanStack Query`（§14.1、§13）。这个组合支持 Prompt-first、Workspace-oriented 的复杂工作台，Tailwind 负责快速构建三列工作台与结构化侧栏，样式实现必须以 `ux/` 目录中的原型为基线抽象出 design tokens 和共享组件，而不是回退到通用后台模板。
- **Desktop Client**：`Electron + React + TypeScript + local-agent-runtime`。Electron 作为桌面壳层承接本地 UI、权限弹窗、系统托盘、自动更新和 IPC；`local-agent-runtime` 作为完整 Edge Agent 的运行时，负责本地推理、本地 Skill 编排、本地队列与本地证据汇总。若后续对体积和安全边界要求进一步提高，可在保持本地执行层独立的前提下迁移壳层到 Tauri。
  - 首发范围说明：中心端 `Agent Loop` 是首发主路径；Desktop 端首发以本地执行、本地产物与同步为主，独立长生命周期 Agent Loop 归入 `Phase 2+`。
- **本地执行层**：`local-agent-runtime` 建议独立于 UI 壳，首版默认使用 `Node.js/TypeScript` 作为本地能力协调进程，负责文件系统、桌面应用、浏览器、剪贴板、下载目录、凭证注入、离线缓存与边缘 Agent 编排；只有在特定本地自动化、OCR 或系统适配器确实需要时，再通过 sidecar 引入 Python，不把这些职责塞回前端壳层。
- **执行层**：`Node.js/TypeScript + Playwright Test`（§14.1、§9.6），作为脱离推理层的确定性 runner，专门执行 `automation.generate` 产出的 Playwright 资产并返送 Logs/断言/痕迹；Web 端网页自动化与 Desktop Client 的本地自动化共享同一执行证据模型。
- **存储**：`PostgreSQL` 存对象模型、版本/会话/审批状态、设备与会话元数据；`MinIO` 存 Raw Assets、UX/文档/执行产物、本地同步产物等大文件（§4.1、§7.3、§14.1）。
- **索引/解析**：`OpenGrok`（代码导航）+ `Tree-sitter`（AST/增量解析）支撑 Code Intelligence，Knowledge Intelligence 通过文档切块+元数据索引完成（§7.3）。首轮建设不把向量层作为核心依赖，后续只在召回质量出现明确瓶颈时再引入语义检索增强层。

前端视觉与交互实现以 [ux/index.html](/Users/uben/project/project/Nasus/ux/index.html)、[ux/styles.css](/Users/uben/project/project/Nasus/ux/styles.css)、[ux/app.js](/Users/uben/project/project/Nasus/ux/app.js) 为直接实现基线，[docs/frontend-visual-style.md](/Users/uben/project/project/Nasus/docs/frontend-visual-style.md) 作为高层视觉说明补充。后续正式前端必须保留 `ux/` 原型确立的三列壳层、深色 token、对话优先和结构化右侧面板语言，并将其工程化为 React 组件、主题变量和状态模型。与此同时，前后端交互必须采用 `agent-first + tool-first` 模式：主会话是第一入口，页面按钮、快捷 chip、右侧卡片动作和 Desktop 动作都只是同一套 `ToolInvocation` 的不同触发方式。

## 3 前端信息架构与页面职责
- **导航模型**：当前 canonical 信息架构不再使用 `Home/Tasks/Knowledge/Runs/Settings` 这一旧命名，而是按原型收敛为三层：
  - `L0`：`Welcome`
  - `L1`：`Build`、`Dashboard`、`Documentation`
  - `L2`：进入具体项目后的 `Project Space`
- **Build**：项目创建与初始化入口，主屏突出 `Create Project` 大卡、导入入口和对话式引导。它不承担项目组合浏览职责。
- **Dashboard**：全量项目仪表盘，显示项目卡片、全局进展、风险、待审批项和失败趋势。点击项目卡后下钻到独立 `Project Space`，左侧导航整体替换为项目空间菜单。
- **Documentation**：一级产品区，承接平台说明、概念、方法论、模板和帮助，不是低频 footer 链接。
- **Project Space**：项目内工作区集合，包含 `Project Overview`、`Version Space`、`Version Create`、`Personal Workspace`、`Knowledge Gallery`、`Knowledge Detail`、`Runs`、`Run Detail`、`Governance`、`Approval Detail`、`Release Readiness`、`Desktop`。这些页面的布局、组件和右栏映射详见 [docs/frontend-page-blueprints.md](/Users/uben/project/project/Nasus/docs/frontend-page-blueprints.md)。
- **Personal Workspace**：最核心的 `agent-first` 质量工作台，承接 `Task Context Workspace`、`Quality Assurance Profile`、`QualityAssetPack` 和 `Agent Goal`。界面必须同时展示对话流、结构化资产、工具进度、冲突状态和 Agent Loop。
- **Agent Goal UI**：不再是一行补充要求，而是正式页面组件。前端必须实现：
  - 目标状态 badge
  - step rail / 进度条
  - `thinking/observing/planning/waiting` 卡片
  - `interrupt/resume/cancel/feedback` 操作
  - `AgentGoal` 与消息流混排的卡片渲染
- **Knowledge / Runs / Governance**：不只是三个一级壳层，而是包含列表页和详情页的工作区族群。各页面的右栏 tab、详情态和返回规则必须与原型一致，不能再统一假设所有页面都使用 `Assets / System / Runs`。
- **Desktop Client**：桌面工作台与 Web 共用任务模型，但把本地 Tool 面板、设备状态、本地权限申请、本地产物、远程任务确认和离线队列作为一等界面对象；它不替代 Web 的组织级协作面，而是承接本地执行与本地感知。
- **Tool 可见性**：Web 与 Desktop 默认都展示统一工具列表；Skill 可作为高级视图中的内部能力标签展示，但产品级动作必须以 `ToolDefinition` 为准。是否可执行由 `RBAC + policy + capability grant` 联合决定；高风险工具在 UI 上需要明确展示确认要求与限制条件。
- **状态同步**：Web 与 Desktop 都通过 TanStack Query 或等价状态层同步后端 `Conversation / ToolInvocation / Task / Run / Device` 状态，前者偏组织级协作状态，后者偏本地执行状态。两端都要保留 `conversationId` 和 `taskContextId` 的主键语义，但 Desktop 允许额外缓存本地队列和离线产物。

### 3.1 门户壳层与路由布局

- Web Portal 采用统一三列壳层：左侧导航承载全局入口，中间主画布承载页面内容，右侧 inspector/setting rail 承载策略、证据过滤、环境和审批动作。以 `ux/` 原型为基线，桌面端和 Web 端都应优先保留 `220px` 左侧栏、`56px` 顶栏、`300px` 右侧上下文面板这一组主尺寸，除非明确进入窄屏断点。
- `Welcome`、`Build`、`Dashboard`、`Documentation` 共用顶层壳层；进入 `Project Space` 后左侧导航整体替换为项目内菜单，形成明确的下钻感，而不是在外层导航下方内联展开二级菜单。
- 主工作区内部不再额外挂全局 header，而是由每个页面提供局部标题栏和次级动作区，这一点直接参考 AI Studio 当前的内容型头部结构。
- 底部输入框采用共享组件 `ActionComposer`：`Build` 中用于“创建项目/接入资产/初始化系统画像”，`Dashboard` 中用于“询问全局进展与风险”，`Personal Workspace` 中用于“追加上下文并继续分析”，`Runs` 中用于“请求归因/重跑/提交放行”。该组件必须保留 `ux/` 原型中的渐变 focus 边框、多行输入、自适应高度、左侧工具按钮、右侧发送按钮和底部状态提示。
- Desktop Client 采用双层壳层：上层是 UI Shell，下层是 `Local Capability Host`。UI Shell 只负责桌面任务视图、权限弹窗、离线队列和本地状态展示；`Local Capability Host` 负责文件系统、桌面应用、浏览器、证书、剪贴板、下载目录与本地自动化执行。
- 响应式规则：`>= 1440px` 维持 Web 三列与 Desktop 三段式主视图；`768px - 1439px` 把右侧 rail 收为抽屉；`< 768px` 将左侧导航和右侧策略面板都改为覆盖层。Desktop Client 在窄窗口下优先保留本地任务队列和执行状态，而不是强行压缩全部控制面。

### 3.2 基于 ux 原型的视觉与交互基线

- `ux/` 目录中的原型是后续前端开发的样式和布局基线，不是一次性演示稿。正式实现必须先抽取其 CSS 变量、布局尺度、组件模式和状态行为，再映射到 React 组件与主题系统。
- 视觉 token 必须至少覆盖以下语义层：`bg-base`、`bg-surface`、`bg-elevated`、`bg-hover`、`border-subtle`、`border-default`、`text-primary`、`text-secondary`、`text-tertiary`、`accent-blue`、`accent-purple`、`accent-green`、`accent-amber`、`accent-red` 以及输入框渐变边框使用的 `gradient-start / mid / end`。这些 token 应沉淀到设计系统主题，而不是散落为 Tailwind arbitrary values。
- 风格基调固定为 dark-first、低对比 chrome、轻量发光 accent、细边框和中等圆角。通用组件基准值沿用原型：主卡片 `10px - 12px` 圆角、常规卡片 `12px - 14px` 内边距、图标按钮 `32px`、消息头像/Agent 图标 `28px`、资产图标 `22px`。
- 页面信息组织固定为 conversation-first：中间画布优先承载消息流、结构化结果卡、建议动作 chip 和 typing/progress 状态；右侧面板作为“上下文侧车”，但 tab 配置必须按页面定义。完整映射表以 [docs/frontend-page-blueprints.md](/Users/uben/project/project/Nasus/docs/frontend-page-blueprints.md) 为准，不允许所有页面强行复用同一组 tab。
- 消息流必须支持混合内容：自然语言段落、内嵌 impact/scenario 卡片、状态 badge、进度条、建议动作 chip、代码或术语高亮、后续动作按钮。Agent 输出不能退化为纯文本列表。
- 交互细节必须保留：消息进入动画、typing dots、输入区 focus 渐变、pill chip hover/active、右侧 tab active 态、进度条渐进更新、自定义 scrollbar 和轻量 tooltip。
- 工程实现上禁止沿用原型中的 inline CSS 和直接 DOM 操作。正式前端必须将样式收敛为设计 token、共享 class 或组件封装；交互行为收敛为 React state/store，而不是在页面里散落 `querySelector` 与 `style.display` 逻辑。
- 组件拆分至少包括：`WorkspaceShell`、`GlobalNav`、`WorkspaceNav`、`PageHeader`、`ChatTimeline`、`UserMessage`、`AgentMessage`、`StructuredMessageCard`、`ActionComposer`、`RightPanelTabs`、`ProjectCard`、`VersionCard`、`USBoard`、`USCard`、`RunCard`、`ApprovalCard`、`ReleaseReadinessPanel`、`FailureTimelineCard`、`EvidenceCard`、`DiffViewer`、`ProgressRing`、`ToolPalette`、`ToolInvocationTimeline`、`ConflictPanel`、`AgentGoalCard`、`AgentStepRail`、`ThinkingCard`。这些组件需要在 Web 和 Desktop 之间最大化复用。

### 3.3 前后端模块边界

| 前端职责 | 后端接口 | 数据契约 |
| --- | --- | --- |
| `Build` / `Dashboard` / `Personal Workspace` 发起会话、触发工具、显示上下文和冲突状态 | `POST /v1/conversations/{id}/messages`、`GET /v1/conversations/{id}/events`、`GET /v1/tools/catalog`、`POST /v1/tool-invocations`、`GET /v1/tasks/{id}`、`GET /v1/tasks/{id}/conflicts`、`GET /v1/features/{featureId}/context` | `ConversationSession`、`ToolDefinition[]`、`ToolInvocation[]`、`TaskContext`、`QualityProfile`、`FeatureContext`、`AgentDecision[]` |
| `Knowledge` 展示对象图谱、证据，支持 Candidate 审批请求与合并结论查看 | `GET /v1/objects/{id}`、`POST /v1/approvals` | `ContextObject` 关系结构、`ApprovalRequest`、`MergedResolution` |
| `Runs` 展示执行、回放、失败归因、patch 建议和通道过滤 | `POST /v1/runs`、`GET /v1/runs/{id}`、`POST /v1/failure` | `Run`、`ExecutionEvidence`、`FailureReport` |
| `Build` / `Project Overview` / `Documentation` 管理项目接入、Provider、策略和权限说明 | `GET/POST /v1/projects`、`GET /v1/policies`、`POST /v1/policies` | `ProjectConfig`、`PolicyDefinition` |
| `Desktop Client` 发起本地权限申请、触发本地工具、同步本地执行状态、上传本地产物 | `GET /v1/tools/catalog`、`POST /v1/tool-invocations`、`POST /v1/devices/register`、`POST /v1/device-sessions`、`POST /v1/sync`、`POST /v1/runs`、`POST /v1/capabilities/negotiate` | `ToolDefinition[]`、`ToolInvocation[]`、`DeviceProfile`、`DeviceSession`、`SyncEvent`、`LocalRunArtifact`、`CapabilityGrant`、`AgentDecision` |

### 3.4 组件与状态

- `Personal Workspace` 中的状态控件：`草稿`、`分析中`、`待审阅`、`已收敛`，按钮依赖状态启用重生成/执行准备动作；所有写动作都必须能回溯到 `toolInvocationId`。
- `Knowledge` 的对象详情侧栏保持两个层级：`对象元数据` + `证据轨迹`；证据链由 Evidence Card 列表 + control panel 过滤。
- `Runs` 提供执行时间线、环境快照标签、失败归因标签、patch 建议卡片，并支持按 `已完成/失败/待放行` 和 `execution_channel` 过滤。
- `Build` 和 `Project Overview` 承接项目初始化、Connector 和 Provider 配置；策略与审批说明则通过 `Governance`、`Documentation` 和独立配置面板承接，所有编辑操作走审批流程。
- `Desktop Client` 的状态分为 `设备在线`、`等待授权`、`执行中`、`pending_merge`、`离线待补传`、`受限模式`，界面必须显式显示本地能力可用性、当前权限范围、同步滞后和远程任务确认状态。
- `ChatTimeline` 需要显式支持 `user`、`agent`、`typing`、`structured-result` 四类消息节点，并保留阶段推进能力，例如“先输出场景卡，再输出生成脚本过程说明”。消息节点应由 `phase`、`messageType` 和 `relatedToolInvocationId` 驱动，而不是只靠 markdown 文本渲染。
- 右侧上下文面板必须有独立状态片：`activeContextTab`、`scenarioProgress`、`scenarioStatusLabel`、`selectedAssetId`、`selectedRunId`。这些状态由 store 管理，并允许被 Agent 响应或运行事件流增量更新。
- `ActionComposer` 必须管理 `inputValue`、`isFocused`、`autoHeight`、`isWaitingForAgent`、`sendEnabled` 五类本地状态；`Enter` 发送、`Shift+Enter` 换行、发送时锁定输入和快捷动作、响应返回后恢复输入是硬约束。
- 建议动作 chip 不只是装饰元素，而是前端 action registry 的可视化入口。每个 chip 至少绑定 `actionId`、`label`、`icon`、`targetToolId`、`disabledReason`，执行时要能统一进入 `ToolInvocation` 调用链，并在执行期间锁定其他互斥动作。

### 3.5 页面组件组成

| 页面 | 主要组件 | 前端数据源 | 关键交互 |
| --- | --- | --- | --- |
| `Welcome` | Hero 标题、能力卡片、最近项目、最近版本、最近会话、底部 `ActionComposer` | `ProjectSummary[]` `VersionSummary[]` `ConversationSession[]` | 进入 Build、进入 Dashboard、恢复会话 |
| `Build` | `Create Project` 大卡、导入模块、初始化计划、项目创建会话、底部 `ActionComposer` | `ProjectDraft` `ConnectorBinding[]` `ConnectorRun[]` | 创建项目、导入 Git/US/UX、初始化系统画像 |
| `Dashboard` | 全局统计、项目卡片网格、阻塞列表、快捷问询 chips、底部 `ActionComposer` | `ProjectPortfolioCard[]` `RiskRollup` `ApprovalSummary` `RunSummary` | 打开项目、查询进展、查看风险 |
| `Documentation` | 文档 Hero、分类卡片、模板、示例、底部 `ActionComposer` | `DocTopic[]` `TemplateSummary[]` | 搜索文档、查看模板 |
| `Project Overview` | 项目头部、系统画像摘要、连接源、活跃版本、项目会话 | `Project` `BaselineSummary` `ConnectorRun[]` `VersionSummary[]` | 创建版本、刷新系统画像 |
| `Version Space` | 版本头部、`USBoard`、版本风险卡、待执行/待审批列表、会话区 | `Version` `USWorkItem[]` `RiskSummary` | 查看 US、分配负责人、进入个人工作台 |
| `Version Create` | 创建向导、US 导入、负责人分配、基线 fork 预览、会话区 | `VersionDraft` `USImportPreview` `OwnerAssignment[]` | 创建版本、导入 US、fork 基线 |
| `Personal Workspace` | US 头部、`ChatTimeline`、`QualityAssetPack` 画布、`Tool Palette`、`Tool Invocation Timeline`、`Conflict Panel`、`Agent Goal`、底部 `ActionComposer` | `ConversationSession` `ToolInvocation[]` `TaskContext` `QualityProfile` `QualityAssetPack` `AgentDecision[]` `AgentGoal[]` | 发起分析、触发工具、局部重生成、处理中断、跳转执行 |
| `Knowledge Gallery` | 图谱/列表切换、对象列表、搜索、会话区 | `ContextObject[]` `FeatureContext` | 搜索对象、进入对象详情 |
| `Knowledge Detail` | 对象头部、关系、证据、历史、会话区 | `ContextObject` `EvidenceRef[]` `ApprovalRequest[]` | 查看证据、发起晋级 |
| `Runs` | 执行列表、过滤条、失败摘要、会话区 | `Run[]` `FailureReport[]` | 打开运行、按通道过滤 |
| `Run Detail` | Timeline、Logs、Trace、Evidence、Failure Analysis、Healing、会话区 | `Run` `ExecutionEvidence[]` `FailureReport` `ReleaseAdvice` | 重跑、查看 trace、生成修复建议 |
| `Governance` | 待审批列表、待 merge 列表、策略阻塞、会话区 | `ApprovalRecord[]` `MergedResolution[]` | 进入审批、进入放行面板 |
| `Approval Detail` | diff 审阅、冲突字段、审批动作、会话区 | `ApprovalRecord` `MergedResolution` `ConflictPayload` | 审批、拒绝、接受自动 merge |
| `Release Readiness` | 评分摘要、阻塞项、执行健康、知识晋级状态、会话区 | `ReleaseAdvice` `ApprovalRecord[]` `RiskSummary` | 生成放行建议、提交放行 |
| `Desktop` | 本地队列、能力授权、同步健康、本地会话区 | `DeviceSession` `CapabilityGrant[]` `SyncEvent[]` | 确认本地任务、重试同步 |
| `Desktop Client` | 设备状态卡、权限申请卡、本地 `Tool Palette`、本地任务队列、本地执行面板、远程任务确认面板、同步状态条、离线补传面板 | `ConversationSession` `ToolDefinition[]` `ToolInvocation[]` `DeviceSession` `CapabilityGrant` `LocalTask` `LocalRunArtifact` `AgentDecision[]` | 申请权限、执行本地任务、确认远程动作、查看同步状态、补传产物 |

## 4 后端分层与服务边界
- **Tool-first Orchestration Layer**：`Conversation Orchestrator` + `Tool Registry` + `Tool Invocation Runtime` + `Central Orchestrator Agent` + `Durable Workflow Runtime` + `Agent Graph Runtime` + `Skill Registry` + `Worker Scheduler` + `Merge/Score` + `Approval Control`。这层接收用户发起的会话、按钮、桌面动作或外部 API 请求，先转成工具调用，再规划阶段、路由 skill、调度 worker，收敛结果并推进审批。
- **Domain Intelligence Layer**：Baseline/Change Impact/Verification Planning/Scenario/Case/Automation/Failure Analysis/Healing/Release Advice（§9）。每个服务清楚边界：Baseline 生成 `Official/Version Working Baseline`，Impact 产出变更影响，Verification 产出验证计划，Automation 负责 Playwright 资产，Failure/Healing 负责执行证据归因与 patch 建议，Release Advice 输出上线准备度。
- **Unified Context Engine**：负责 Source Connectors、Code/Knowledge Intelligence、Anchor Extraction、Entity Resolution、Context Assembler、Context Object Store（§7）。当前工程建议对工作台不直接暴露底层 `search_code/search_docs`，而是通过统一能力封装；若后续按最终特性说明书支持 Agent 原生检索与执行，也必须通过策略网关、审计事件和证据落点统一收口。
- **Integration Fabric**：Asset ingestion、Execution、Storage、Review/Policy、Provider Contracts、Adapter Registry（§8.2）。所有外部系统接入（Git、Docs、OpenAPI、执行器、存储）必须通过防腐层进到统一上下文引擎/域服务。
- **设备与桌面运行层**：Device Registry、Device Session Service、Sync Service、Capability Policy Service、Artifact Upload Service、`Edge Agent Runtime`。它们负责设备注册、设备会话、任务下发、心跳、权限下发、离线补传和桌面执行证据回传。
- **治理与知识流转**：Project/Version/Session/Baseline + Official/Version Shared/Session-only/Candidate Knowledge（§6）。API 设计应强制标明知识所属层级，`Candidate Knowledge` 默认先经审批进入 `Version Shared Knowledge`，版本收口后再回写 `Official Baseline`。桌面端产物可同步为候选知识，但默认不绕过治理流。

### 4.1 后端服务拆分

| 服务 | 主要职责 | 接口示例 | 状态/事件 |
| --- | --- | --- | --- |
| `Baseline Service` | 管理 Official/Version Working/Version Shared 基线，Candidate 晋级 | `POST /v1/baselines`、`PATCH /v1/baselines/{id}` | `baseline_created`、`baseline_promoted` |
| `Conversation Service` | 管理主会话、消息流和会话级事件输出 | `POST /v1/conversations/{id}/messages`、`GET /v1/conversations/{id}/events` | `conversation_message_created`、`conversation_summary_updated` |
| `Tool Registry Service` | 维护 `ToolDefinition`，暴露工具目录、风险和确认要求，并映射内部 Skill | `GET /v1/tools/catalog` | `tool_catalog_published` |
| `Tool Invocation Service` | 统一处理 `ToolInvocation`，请求中心或边缘执行，并驱动 gate 与 workflow | `POST /v1/tool-invocations`、`GET /v1/tool-invocations/{id}` | `tool_invoked`、`tool_waiting_confirmation`、`tool_completed` |
| `Agent Decision Service` | 存储中心端与桌面端的 `AgentDecision`，推进 provisional 流 | `POST /v1/agent-decisions`、`GET /v1/tasks/{id}/decisions` | `decision_created`、`decision_superseded` |
| `Conflict Resolution / Merge Service` | 检测冲突、生成 `MergedResolution`、驱动 `pending_merge` 生命周期 | `GET /v1/tasks/{id}/conflicts`、`POST /v1/conflicts/{id}/merge` | `conflict_detected`、`resolution_merged` |
| `Change Impact Service` | 分析变更、构建 Change Set、输出回归范围 | `POST /v1/impacts`、`GET /v1/impacts/{id}` | `impact_analyzed` |
| `Verification Planning Service` | 生成验证计划、策略、自动化建议 | `POST /v1/verification_plans` | `verification_plan_ready` |
| `Scenario/Case Service` | 生成场景、用例、断言链 | `POST /v1/scenarios`、`POST /v1/cases` | `scenario_generated` |
| `Automation Service` | 转换 QA Profile 为 Playwright 资产，协调 Runner | `POST /v1/automations`, `POST /v1/runs` | `automation_triggered`、`run_created` |
| `Failure & Healing Service` | 失败分类、归因、patch 提议 | `POST /v1/failures`, `POST /v1/healings` | `failure_resolved`, `healing_proposed` |
| `Release & Approval Service` | 生成放行建议、审批 Candidate 晋级 | `POST /v1/release_advice`, `POST /v1/approvals` | `release_assessed`, `approval_completed` |
| `Device Registry Service` | 注册设备、管理设备身份与信任状态 | `POST /v1/devices/register`、`GET /v1/devices/{id}` | `device_registered`、`device_trusted` |
| `Device Session Service` | 维护桌面会话、心跳、在线状态和权限范围 | `POST /v1/device-sessions`、`PATCH /v1/device-sessions/{id}` | `device_session_opened`、`device_heartbeat`、`device_offline` |
| `Sync Service` | 合并桌面端状态、同步事件、离线补传队列 | `POST /v1/sync`、`GET /v1/sync/{scope}` | `sync_requested`、`sync_applied`、`sync_replayed` |
| `Capability Policy Service` | 申请并发放本地能力授权 | `POST /v1/capabilities/negotiate`、`POST /v1/capabilities/grant` | `capability_requested`、`capability_granted`、`capability_revoked` |

### 4.2 接口语义与契约

- `POST /v1/conversations/{id}/messages`：主会话的 canonical 入口，请求体包含自然语言输入、显式上下文引用和可选的目标工具提示；系统返回消息接收确认，并通过事件流回传 `ToolInvocationPlan`、工具执行过程和结构化结果。
- `GET /v1/conversations/{id}/events`：返回主会话消息、工具调用计划、工具执行状态和推荐后续动作。
- `GET /v1/tools/catalog`：返回 `ToolDefinition[]`，必须包括 `tool_kind`、`scope`、`risk_level`、`confirmation_mode`、`required_context`。
- `POST /v1/tool-invocations`：写操作的 canonical command surface，Web、Desktop 和外部 API 都可调用；需携带 `conversationId`、`toolId`、`initiatorSurface`、`targetScope`、`inputPayload`、`inputEvidenceRefs`，系统返回 `toolInvocationId` 并按需要进入 `waiting_confirmation` 或 `waiting_approval`。
- `GET /v1/tool-invocations/{id}`：返回工具调用状态、结构化结果、对象引用和后续推荐工具。
- `POST /v1/tasks`：保留为领域对象写入边界，用于少量需要显式创建任务对象的系统流程；其写路径仍应由会话或工具调用驱动。
- `GET /v1/tasks/{id}/conflicts`：返回当前任务的冲突列表、双端 `AgentDecision` 和推荐合并方案。
- `POST /v1/runs`：提交 `automationId`、`environmentId`、`retryPolicy`、`execution_channel`，Runner 或 Desktop 通道输出 `runId`、`status`、`evidenceRefs`。
- `POST /v1/approvals`：包含 `candidateId`、`baselineTarget`、`approvalNotes`、`overrideFlag`；审批完成后触发 `baseline_promoted`.
- `POST /v1/devices/register`：Desktop Client 首次注册设备身份、版本和能力摘要，返回设备信任状态与初始策略。
- `POST /v1/device-sessions`：打开一次桌面设备会话，绑定用户、设备、组织和权限范围。
- `POST /v1/sync`：桌面端提交本地状态、离线事件、同步检查点和待补传产物索引。
- `POST /v1/capabilities/negotiate`：设备与服务端协商可用本地能力，返回允许执行的能力集合与限制条件。
- 所有 UI 写动作都必须能回溯到 `toolInvocationId`；对象查询类接口作为 read model 存在，但不再是主业务动作入口。

### 4.3 长任务与实时事件通道

- Web Portal 到 Orchestrator 的命令链路采用“`Conversation + ToolInvocation` 写入口 + Read API 查询”模式；任务分析、工具执行进度、审批状态更新使用 SSE 作为默认实时通道，避免在首版引入过重的双向状态同步。
- Desktop Client 与 Orchestrator 之间需要双通道：控制命令走 REST，设备心跳、同步事件、队列进度和补传状态走 SSE 或轻量 WebSocket 事件流。若首版不做 WebSocket，也要保留事件流抽象。
- 建议提供 `GET /v1/tasks/{taskId}/events`、`GET /v1/runs/{runId}/events`、`GET /v1/approvals/{approvalId}/events`、`GET /v1/device-sessions/{id}/events`、`GET /v1/sync/events` 三类以上事件流接口，前端通过 TanStack Query + Event reducer 合并实时状态；Desktop 端保持“REST + 事件流抽象，SSE 为基线，WebSocket 作为后续扩展”。
- 文件上传采用 MinIO 预签名上传，前端只向后端申请上传凭据和对象元数据；Runner、Worker、Web Portal、Desktop Client 都通过 `evidenceRef` 关联二进制产物。本地私有文件默认不上传，上传必须显式由策略或用户动作触发。
- 只有在后续确实出现多人协同编辑、共享游标、交互式回放控制等需求时，再引入 WebSocket；当前开发基线不依赖 WebSocket，但桌面端本地动作状态必须保留事件化模型。

### 4.4 前端 SSE 消费与状态合并规范

- 前端不得把 SSE 当作“提示刷新”的弱通知流；SSE 必须作为 `Conversation`、`ToolInvocation`、`Task`、`Run`、`Approval`、`DeviceSession` 六类对象的增量状态来源。
- 每条 SSE 事件除通用信封外，还必须携带：
  - `entity_type`
  - `entity_id`
  - `entity_version`
  - `mutation_kind=replace|patch|append|invalidate`
  - `patch`
  - `snapshot_hint`
  - `query_keys`
- TanStack Query 只负责 read model cache；真正的事件消费逻辑由前端统一 `EventReducer` 承担。`EventReducer` 负责：
  - 基于 `event_id` 去重
  - 基于 `entity_version` 丢弃乱序旧事件
  - 把 `patch` 合并到本地对象快照
  - 在 `mutation_kind=invalidate` 时触发精确 query 失效，而不是全量 refetch
- 查询键必须固定为：
  - `["conversation", conversationId]`
  - `["task", taskId]`
  - `["task-conflicts", taskId]`
  - `["run", runId]`
  - `["approval", approvalId]`
  - `["device-session", deviceSessionId]`
- 乐观更新只允许用于本地可立即确认的 UI 行为：
  - 会话输入框发送中态
  - 本地 chip/button 的 loading 态
  - 本地队列中待上传 artifact 的占位状态
- 以下对象禁止纯前端乐观写最终状态，必须等待 SSE 或 read model 回写：
  - `Task.status`
  - `Run.status`
  - `MergedResolution`
  - `ApprovalRecord`
  - `CapabilityGrant`
- 查询失效策略固定为：
  - `patch/append` 事件：优先走 reducer 增量合并，不主动 refetch
  - `invalidate` 事件：仅失效事件里显式给出的 `query_keys`
  - `snapshot_hint=true`：触发单对象 refetch，用于合并结果过大、补丁不可逆或版本跳跃
- `Task -> AgentDecision -> Run -> MergedResolution` 这类嵌套对象不得依赖“父对象全量替换”更新，必须按实体维度分别缓存与合并；前端视图层再做组合选择，避免一次 `Task` 事件把 `Run` 和 `MergedResolution` 的局部状态冲掉。
- `ChatTimeline`、`Tool Invocation Timeline`、`Conflict Panel` 都必须订阅同一 reducer 输出，禁止各自独立维护“局部真相”。

## 5 执行层设计
- **Web Runner**：独立 Job/容器，使用 Node.js/TypeScript + Playwright Test（§14.1、§9.6）。它与 `worker-runtime` 解耦，仅接收 `automation.generate` 的执行配置和资产，执行完成后将日志、断言、截图、环境快照回写 MinIO/PostgreSQL。
- **Desktop Local Capability Host**：与 UI 壳分离的本地执行层，接收被授权的本地动作任务，例如文件创建、目录管理、桌面应用操作、浏览器操作、剪贴板、下载目录和本地脚本执行。它把本地动作标准化成 canonical `Run(execution_channel=desktop_local)`、`LocalRunArtifact` 和 `evidence` 再同步回中心端。
- **确定性执行**：Web Runner 不做独立推理，依赖后端策略和 Agent 触发的执行请求；Desktop Client 的本地执行也不直接修改中心正式状态，所有结果都通过统一 `Run(execution_channel=desktop_local)`、本地 artifact 元信息和证据同步回中心。无论请求由页面触发还是由 Agent 原生触发，Failure/Healing worker 都必须消费统一的执行 evidence，输出归因和修复建议（§9.7-9.8）。
- **调度**：`Workflow Runtime` 将执行任务投递到 Queue/Scheduler，Runner 订阅特定任务类型（比如 Playwright automation.run），桌面客户端订阅 `device-scope` 任务类型并在本地执行后回传事件，确保并行但可追踪，符合 “Deterministic Core” 的要求（§2.2、§10.1）。

## 6 存储/索引/解析方案
- **PostgreSQL**：存 Raw Assets 元数据、Context Objects、Baseline Snapshots、Version/Session 状态、Conversation/ToolInvocation、Candidate/Approval 记录、Run Result、Patch/Healing 记录、Device/Device Session/Sync 状态，满足结构化查询与审批逻辑（§4.2、§6.1、§14.2）。
- **MinIO**：存 Raw Assets（代码仓、文档、UX、OpenAPI、历史验证资产、临时材料）和执行产物（Playwright 日志、截图、trace、patch 附件、本地补传 artifact），保证 append-only（§4.1、§12.1）。
- **OpenGrok + Tree-sitter**：OpenGrok 负责代码搜索与跨文件引用，Tree-sitter 负责 AST、符号提取与增量解析，组成 Code Intelligence Backend（§7.3）。Knowledge Intelligence Backend 则通过文档切块 + 元数据索引（可基于 PostgreSQL）支撑文档理解与检索索引（§7.3）。
- **上下文对象存储**：Context Object Store 保存 Candidate/Trusted Objects、Baseline Snapshots、Version Working Baselines（§7.3）；API 调用 `Context Assembler` 时，总是附带证据/置信度/状态，便于前端审计。桌面端的本地产物元数据与同步检查点也应落在此层的索引表里。

### 6.1 数据模型建议

- `TaskContext`：包含 `taskId`, `versionId`, `sessionId`, `relatedFeatures`, `evidenceRefs`, `status`, `lastUpdated`.
- `ConversationSession`：包含 `conversationId`, `spaceType`, `spaceId`, `initiatorId`, `status`, `lastMessageAt`.
- `ToolDefinition`：包含 `toolId`, `toolKind`, `scope`, `riskLevel`, `confirmationMode`, `requiredContext`, `inputSchemaRef`, `outputSchemaRef`.
- `ToolInvocation`：包含 `invocationId`, `conversationId`, `toolId`, `initiatorSurface`, `initiatorActor`, `targetScope`, `status`, `objectRefs`, `evidenceRefs`.
- `QualityProfile`：记录验证范围、impact summary、risk rating、auto/hand-off strategy、linked `taskContextId`.
- `ContextObject`：包含 `id`, `type`, `relationships`, `confidence`, `sourceRefs`, `status` (candidate/trusted), `evidenceSnapshot`.
- `Run`：包含 `runId`, `automationId`, `environment`, `execution_channel`, `status`, `startTime`, `endTime`, `results`, `evidenceRefs`.
- `AgentDecision`：包含 `decisionId`, `taskId`, `source=center|edge`, `decisionKind`, `status=provisional|merged|approved|rejected`, `confidence`, `evidenceRefs`.
- `MergedResolution`：包含 `resolutionId`, `taskId`, `resolutionKind`, `status`, `mergedFromDecisionIds`, `approvalState`.
- `SkillDefinition`：包含 `skillId`, `scope=central|edge|either`, `mappedToolIds`, `internalOnly`.
- `ApprovalRecord`：包含 `candidateId`, `baselineTarget`, `decision`, `approver`, `timestamp`, `notes`.

这些模型必须对齐 `PostgreSQL` schema，且 `MinIO` 仅存其 `evidenceRefs` 指向的大文件。

### 6.2 桌面端补充模型

- `DeviceProfile`：设备标识、客户端版本、操作系统、能力摘要、信任状态。
- `DeviceSession`：设备与用户的一次在线会话，包含心跳时间、权限范围、同步检查点、离线标记。
- `SyncEvent`：桌面端与中心端之间的一次状态同步，包含增量状态、冲突信息、补传队列。
- `LocalRunArtifact`：本地执行产生的产物元信息，包含文件路径、哈希、证据引用、上传状态。
- `CapabilityGrant`：允许设备执行的本地能力集合，例如文件创建、目录管理、浏览器控制、桌面应用控制。

## 7 关键接口与模块边界建议
- `POST /v1/conversations/{id}/messages`：由 `Conversation Orchestrator` 接收自然语言输入，负责理解意图、补足上下文、生成 `ToolInvocationPlan`；返回消息接收确认，并通过事件流回传执行过程。
- `GET /v1/tools/catalog`：返回工具列表、tool_kind、scope、risk、confirmation_mode、required_context，供 Web 与 Desktop 渲染统一工具面板。
- `POST /v1/tool-invocations`：正式公共写入口，由 `Tool Invocation Runtime` 统一执行工具；工具内部再通过 Tool Registry 映射 Skill 和 Worker。
- `GET /v1/features/{featureId}/context`：封装 `get_feature_context`，前端 `Knowledge` 页面用它展示 Feature Graph、Change Graph、相关证据。这是当前工程实现基线，不限制最终产品在 Agent 侧提供更高阶的原生检索能力。
- `GET /v1/tasks/{id}/conflicts`：返回双端 `AgentDecision`、冲突原因和推荐 `MergedResolution`，供 `Personal Workspace`、`Runs` 与 `Desktop Client` 统一展示。
- `POST /v1/runs`：由 Automation Service 或 Desktop 端触发执行，统一创建 canonical `Run`；完成后 evidence 回写 `runs/{runId}`，Failure Worker 订阅同一 run，得出归因并触发 Healing/Release Advice。
- `POST /v1/approvals`：Approval Control 用于处理 `Candidate Knowledge` 的晋级和基线回写。默认路径为 `Candidate -> Version Shared -> Official`，任何晋级或回写动作都必须经过审批，审批结果驱动 Baseline Service 更新。
- `POST /v1/devices/register`：Desktop Client 首次注册设备身份，服务端根据设备、用户、组织和版本返回信任状态、初始策略和客户端配置。
- `POST /v1/device-sessions`：打开桌面设备会话，绑定用户、设备、组织、策略快照和权限范围。
- `POST /v1/sync`：提交桌面端的增量状态、本地任务结果、离线队列和补传检查点。
- `POST /v1/capabilities/negotiate`：对桌面端可执行能力做协商，返回允许的能力集合、限制、需确认项和审计要求。
- **模块边界**：Conversation Orchestrator 负责理解会话和生成工具计划，Tool Invocation Runtime 负责执行工具、进入 gate 并绑定领域对象，Context Engine 负责提供 `taskContext`/`qualityProfile`，Domain Services 负责基于这些上下文产生计划，Skill/Worker Runtime 作为工具背后的内部能力执行层，Runner 专注执行，Desktop Local Capability Host 专注本地能力执行，Integration Fabric 将外部材料/执行/存储统一化。若后续按最终特性说明书演进 Agent 原生直连能力，也必须通过统一策略网关收口，不改变审计与证据主线。

## 8 任务/执行/审批/知识流时序

### 8.1 流程快照

1. `项目接入`：`Build` 发起，`Baseline Service` 建立 Historical/Official 基线，状态从 `draft` -> `ready`.
2. `版本建模`：`Project Overview`/`Version Space` 创建版本，`Change Impact Service` 生成 Change Set，基线状态 `versioning`.
3. `会话启动`：`Personal Workspace` 创建 Session，Status `active`, materials uploaded, context stored in `TaskContext`.
4. `任务分析`：会话先产出 `ToolInvocationPlan`，工具内部再串联 Impact/Verification/Scenario/Case，`QualityProfile` 状态 `analysis`, outputs `verificationPlan`.
5. `双端推理`：中心端与桌面端都可触发工具，工具内部可调用不同 Skill，最终产生 `AgentDecision(status=provisional)`；若结论冲突，任务进入 `pending_merge`。
6. `执行`：`Automation Service` 或 `Desktop Local Capability Host` 统一创建 `Run(execution_channel=web_runner|desktop_local)`，状态 `pending -> running -> complete/fail/pending_merge`。
7. `失败归因`：`Failure Analysis` 消费 `Run`, outputs `FailureReport` + `Healing` suggestions, states `under_review -> pending_merge -> closed`.
8. `放行审批`：`Release Advice` 结合 evidence 和 `MergedResolution`, `Approval Control` 判断 `Decision`, states `pending_merge -> pending -> approved/blocked`.
9. `知识沉淀`：`Approval` 写回 `Version Shared`/`Official`, triggered `baseline_promoted`，双端候选知识先合并后审批。

### 8.2 任务-执行-审批-知识关系

- 所有 `Run` 必须绑定 `taskContextId`；failure/approval 回写都会携带该上下文。
- `Desktop Client` 产生的执行同样必须绑定 `taskContextId` 和 `deviceSessionId`，但正式记录统一写入 canonical `Run`，通过 `execution_channel=desktop_local` 与 `LocalRunArtifact` 识别来源。
- `Knowledge` 页面展示 `Task -> AgentDecision -> Run -> Approval` 时间线，并允许基于 `Candidate` 触发 `Approval`。
- 异常流：若 `Run` 失败且 `failure_classified` 触发 `healing.propose`, UI 提示 `Personal Workspace` 进入重生成并重新走 `automation`.
- 异常流：若桌面端离线，则本地状态进入缓存队列，客户端在恢复连接后补传 `LocalRunArtifact` 与 `SyncEvent`，服务端不得因短暂离线直接丢弃任务状态。
- 异常流：若中心端与桌面端的分析、归因或放行结论冲突，则任务、运行或知识记录进入 `pending_merge`，只有 `MergedResolution` 获批后才能推进正式状态。

### 8.3 开发阶段交付

| 阶段 | 交付物 | 关系 |
| --- | --- | --- |
| Stage 0 | `TaskContext`/`QualityProfile` schema + `Baseline`/`Candidate` contracts | 构建数据管道 |
| Stage 1 | `Build/Project Overview` 项目建档 + `BaselineService` API | 保障接入能力 |
| Stage 2 | `Personal Workspace` 工作台 + `Conversation` / `ToolInvocation` 调用链 + `Automation` 接口 + `Device Registry` 基础接入 | 确保分析闭环 |
| Stage 3 | `Runs` 视图、Runner、Failure/Healing flow + `Desktop Client` 本地执行链路 | 提供执行封装 |
| Stage 4 | `Release Advice` + `Approval` + `Knowledge` 沉淀 + 桌面同步 | 完成治理闭环 |

## 9 分阶段落地建议

1. **Phase 0（对象与协议固化）**：先建 Raw Assets/Context Objects schema、Baseline/Version/Session/Candidate 模型、Unified Context Engine 接口（§15）。至少先搭 PostgreSQL + MinIO + OpenGrok/Tree-sitter + FastAPI 服务，确保数据结构到位。
2. **Phase 1（项目初始化接入）**：实现 Asset Connectors、代码/文档索引、Historical Baseline 生成、管理员校正流程，前端在 `Build / Project Overview / Knowledge` 层提供材料上传与差错展示（§11.1、§12）。
3. **Phase 2（版本与会话机制）**：实现版本 fork、Version Working Baseline、Session-only/Candidate Knowledge 流转、Feature Graph/Change Graph，前端 `Version Space / Personal Workspace` 提供版本/会话切换视图（§11.2-11.4）。
4. **Phase 3（质量方案生成）**：完善 Tool/Skill/Worker 的 impact、verification、scenario、case，`Personal Workspace` 页承接多轮审核与重生成；Agent 需提供 `toolId` 级动作调度和 `ToolInvocation -> Merge/Score` 输出（§14.2、§13.3）。
5. **Phase 4（双端执行）**：构建 automation.generate -> runner -> failure.analysis -> release.assess 范式，同时打通 device registration -> device session -> canonical run write -> sync events，Web 页面展示执行证据，Desktop Client 展示本地执行证据与权限状态（§9.6-9.9、§14.1）。
6. **Phase 5（治理与沉淀）**：实现 Candidate 审批流、Baseline 回写、Official Baseline 更新；`Governance / Knowledge / Project Overview` 提供审批状态与沉淀结果，同时统一桌面端产物补传与审计（§6.3、§12.2）。

整体落地顺序：建议先以单个 project + 2~3 模块建立主链路，采用模块化单体部署（portal、desktop-client、api/orchestrator、worker-runtime、runner + Postgres/MinIO/OpenGrok/Queue）。随着容量增长，再按 context/impact/scenario/failure 分池扩展、runner 变 job、Desktop Local Capability Host 独立服务化、索引脱离在线路径，并逐步补齐更细粒度的治理与策略控制。
