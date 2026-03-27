# Nasus 前端页面蓝图

## 1. 文档定位

本文补齐页面级设计规格，覆盖当前 `ux/` 原型中的 16 个视图、页面层级树、右栏面板映射、核心交互模式和组件目录。

优先级关系：

- 页面结构、页面命名、右栏映射、组件组合以本文为准。
- 前端工程组织、状态分层、测试策略以 [docs/frontend-application-architecture.md](/Users/uben/project/project/Nasus/docs/frontend-application-architecture.md) 为准。
- 前后端对象边界、接口和实时状态协议以 [docs/frontend-backend-design.md](/Users/uben/project/project/Nasus/docs/frontend-backend-design.md) 为准。
- 视觉 token 与壳层风格以 [docs/frontend-visual-style.md](/Users/uben/project/project/Nasus/docs/frontend-visual-style.md) 和 `ux/` 原型为准。

## 2. Canonical 页面层级树

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
  - Desktop
```

规则：

- `Build` 是项目创建和初始化入口，不承担全量项目浏览职责。
- `Dashboard` 是项目组合视图，点击项目卡后进入独立 `Project Space`。
- `Project Space` 是下钻层，进入后左侧导航整体替换为项目内菜单，并提供稳定返回 `Dashboard` 的入口。
- `Personal Workspace` 是单个 US 的核心质量闭环工作台。

## 3. 路由映射

Portal 路由建议：

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
- `/projects/:projectId/desktop`

Desktop 路由建议：

- `/`
- `/tasks/:taskId?`
- `/runs/:runId?`
- `/device`
- `/sync`
- `/settings`

原型当前使用 state-based SPA `viewId`，正式实现需保持下表的一一映射：

| 原型 `viewId` | 正式页面名 | 建议路由 |
| --- | --- | --- |
| `welcome` | Welcome | `/welcome` |
| `build` | Build | `/build` |
| `dashboard` | Dashboard | `/dashboard` |
| `documentation` | Documentation | `/documentation` |
| `projectOverview` | Project Overview | `/projects/:projectId` |
| `versionSpace` | Version Space | `/projects/:projectId/versions` |
| `versionCreate` | Version Create | `/projects/:projectId/versions/new` |
| `personalWorkspace` | Personal Workspace | `/projects/:projectId/workspaces/:usId` |
| `knowledgeGallery` | Knowledge Gallery | `/projects/:projectId/knowledge` |
| `knowledgeDetail` | Knowledge Detail | `/projects/:projectId/knowledge/:objectId` |
| `runs` | Runs | `/projects/:projectId/runs` |
| `runDetail` | Run Detail | `/projects/:projectId/runs/:runId` |
| `governance` | Governance | `/projects/:projectId/governance` |
| `approvalDetail` | Approval Detail | `/projects/:projectId/approvals/:approvalId` |
| `releaseReadiness` | Release Readiness | `/projects/:projectId/release-readiness` |
| `desktop` | Desktop | `/projects/:projectId/desktop` |

## 4. 导航与下钻规则

### 4.1 顶层导航

- 顶层固定显示：`Welcome`、`Build`、`Dashboard`、`Documentation`。
- `Build` 和 `Dashboard` 均保留主会话输入框，但两者的意图域不同：
  - `Build`：创建项目、导入 Git/US/UX、初始化系统画像。
  - `Dashboard`：查询全局项目进展、风险、阻塞项、审批积压。

### 4.2 项目空间导航

- 从 `Dashboard` 点击项目卡后进入项目空间。
- 进入项目空间后，左侧导航整体替换为：
  - `Project Overview`
  - `Version Space`
  - `Personal Workspace`
  - `Knowledge`
  - `Runs`
  - `Governance`
  - `Desktop`
- 左上角必须提供 `← Dashboard` 返回。
- `Version Create`、`Knowledge Detail`、`Run Detail`、`Approval Detail`、`Release Readiness` 属于项目空间内部的详情态，不单列为左侧一级入口，但要保持父导航高亮。

### 4.3 回退规则

- `Project Space -> Dashboard`
- `Version Create -> Version Space`
- `Knowledge Detail -> Knowledge Gallery`
- `Run Detail -> Runs`
- `Approval Detail -> Governance`
- `Release Readiness -> Governance` 或 `Version Space`

## 5. 页面级蓝图

### 5.1 Welcome

- 左栏：产品标识、一级导航。
- 中栏：
  - Hero 标题
  - 能力卡片：`Build`、`Dashboard`、`Documentation`
  - `Recent Projects`
  - `Recent Versions`
  - `Recent Conversations`
  - 底部 `ActionComposer`
- 右栏：
  - `Activity`
  - `Tips`
  - `Status`
- 关键动作：
  - `Enter Build`
  - `Open Dashboard`
  - `Read docs`
  - 会话输入 `Create a new project`

### 5.2 Build

- 左栏：一级导航。
- 中栏：
  - `Create Project` Hero 卡
  - `Project Profile`
  - `Source Imports`
  - `Initialization Plan`
  - `Draft Projects`
  - 会话引导区
  - 底部 `ActionComposer`
- 右栏：
  - `Projects`
  - `Imports`
  - `Health`
- 关键动作：
  - `Create Project`
  - `Validate Sources`
  - `Import Git`
  - `Import US Docs`
  - `Import UX Boards`
  - `Initialize System Image`

### 5.3 Dashboard

- 左栏：一级导航。
- 中栏：
  - 全局统计卡
  - 项目卡片网格
  - 风险与阻塞列表
  - 快捷问询 chips
  - 底部 `ActionComposer`
- 右栏：
  - `Alerts`
  - `Progress`
  - `Activity`
- 关键动作：
  - `Open Project`
  - `Open governance backlog`
  - `Check quality progress`

### 5.4 Documentation

- 左栏：一级导航。
- 中栏：
  - 文档 Hero
  - 文档分类卡片
  - `Templates`
  - `Examples`
  - 底部 `ActionComposer`
- 右栏：
  - `Topics`
  - `Templates`
  - `Updates`

### 5.5 Project Overview

- 左栏：项目空间导航。
- 中栏：
  - 项目摘要
  - `Official System Image`
  - `Connected Sources`
  - `Active Versions`
  - `Recent Risk Signals`
  - 项目级会话区
- 右栏：
  - `Context`
  - `Assets`
  - `Activity`
- 关键动作：
  - `Create Version`
  - `Refresh System Image`
  - `Open Knowledge`

### 5.6 Version Space

- 左栏：项目空间导航。
- 中栏：
  - 版本头部
  - `US Board`
  - 版本风险摘要
  - `Pending Execution`
  - `Pending Approval`
  - 会话区
- 右栏：
  - `Board`
  - `Risk`
  - `Activity`
- 关键动作：
  - `Create Version`
  - `Import US`
  - `Assign Owners`
  - `Generate Version Risk`

### 5.7 Version Create

- 左栏：项目空间导航，`Version Space` 高亮。
- 中栏：
  - 创建向导头部
  - `Version Basics`
  - `Source Branch`
  - `US Import`
  - `Owner Assignment`
  - `Baseline Fork Preview`
  - 会话区
- 右栏：
  - `Summary`
  - `Owners`
  - `Fork`
- 关键动作：
  - `Import US`
  - `Assign Owners`
  - `Fork Baseline`
  - `Create Version`

### 5.8 Personal Workspace

- 左栏：项目空间导航。
- 中栏：
  - US 头部
  - `ChatTimeline`
  - `Quality Asset Pack` 主工作区
  - `Agent Goal` 区
  - 底部 `ActionComposer`
- 右栏：
  - `Assets`
  - `System`
  - `Runs`
- 关键动作：
  - `Generate Scenarios`
  - `Generate Cases`
  - `Generate Automation`
  - `Send to Execution`
  - `Approve Asset`
  - `Regenerate`

### 5.9 Knowledge Gallery

- 左栏：项目空间导航。
- 中栏：
  - 图谱/列表切换
  - 对象列表
  - 搜索条
  - 会话区
- 右栏：
  - `Graph`
  - `Objects`
  - `Search`
- 关键动作：
  - `Inspect Object`
  - `Analyze Impact`
  - `Promote Candidate`

### 5.10 Knowledge Detail

- 左栏：项目空间导航，`Knowledge` 高亮。
- 中栏：
  - 对象头部
  - `Overview`
  - `Relationships`
  - `Evidence`
  - `History`
  - 会话区
- 右栏：
  - `Context`
  - `Evidence`
  - `Activity`
- 关键动作：
  - `Compare Branches`
  - `Open Evidence Trail`
  - `Promote Candidate`

### 5.11 Runs

- 左栏：项目空间导航。
- 中栏：
  - 运行筛选头部
  - 运行列表
  - 执行状态过滤
  - 会话区
- 右栏：
  - `Active`
  - `History`
  - `Failed`
- 关键动作：
  - `Open Run`
  - `Filter by Channel`
  - `Review Failures`

### 5.12 Run Detail

- 左栏：项目空间导航，`Runs` 高亮。
- 中栏：
  - Run 头部
  - `Timeline`
  - `Logs`
  - `Trace`
  - `Evidence`
  - `Failure Analysis`
  - `Healing`
  - 会话区
- 右栏：
  - `Evidence`
  - `Failure`
  - `Activity`
- 关键动作：
  - `Retry Run`
  - `Open Trace`
  - `Propose Healing Patch`
  - `Jump to US`

### 5.13 Governance

- 左栏：项目空间导航。
- 中栏：
  - 治理头部
  - `Pending approvals`
  - `Pending merge`
  - `Release gate`
  - 会话区
- 右栏：
  - `Pending`
  - `Resolved`
  - `Policy`
- 关键动作：
  - `Open Approval`
  - `Open Release Readiness`
  - `Review Policy Blockers`

### 5.14 Approval Detail

- 左栏：项目空间导航，`Governance` 高亮。
- 中栏：
  - 审批头部
  - `Object Summary`
  - `Base / Mine / Theirs`
  - `Conflict Fields`
  - `Approval Actions`
  - 会话区
- 右栏：
  - `Diff`
  - `Evidence`
  - `History`
- 关键动作：
  - `Approve`
  - `Reject`
  - `Accept Auto Merge`
  - `Resolve Manually`

### 5.15 Release Readiness

- 左栏：项目空间导航，`Governance` 高亮。
- 中栏：
  - 放行头部
  - `Score Summary`
  - `Blocking Issues`
  - `Execution Health`
  - `Knowledge Promotion Status`
  - 会话区
- 右栏：
  - `Blockers`
  - `Signals`
  - `Activity`
- 关键动作：
  - `Generate Release Advice`
  - `Submit Release Gate`
  - `Open Blockers`

### 5.16 Desktop

- 左栏：项目空间导航。
- 中栏：
  - 设备状态头部
  - `Local Queue`
  - `Capability Grants`
  - `Sync Health`
  - 会话区
- 右栏：
  - `Queue`
  - `Grants`
  - `Sync`
- 关键动作：
  - `Confirm Local Task`
  - `Reject`
  - `Retry Sync`
  - `View Local Evidence`

## 6. 右栏面板映射表

| 页面 | 右栏标题 | Tabs |
| --- | --- | --- |
| Welcome | Studio Overview | `Activity` `Tips` `Status` |
| Build | Build Context | `Projects` `Imports` `Health` |
| Dashboard | Global Signals | `Alerts` `Progress` `Activity` |
| Documentation | Docs Navigator | `Topics` `Templates` `Updates` |
| Project Overview | Project | `Context` `Assets` `Activity` |
| Version Space | Version | `Board` `Risk` `Activity` |
| Version Create | Version Draft | `Summary` `Owners` `Fork` |
| Personal Workspace | Workspace | `Assets` `System` `Runs` |
| Knowledge Gallery | Knowledge | `Graph` `Objects` `Search` |
| Knowledge Detail | Object Detail | `Context` `Evidence` `Activity` |
| Runs | Runs | `Active` `History` `Failed` |
| Run Detail | Run Detail | `Evidence` `Failure` `Activity` |
| Governance | Governance | `Pending` `Resolved` `Policy` |
| Approval Detail | Approval | `Diff` `Evidence` `History` |
| Release Readiness | Release Gate | `Blockers` `Signals` `Activity` |
| Desktop | Desktop | `Queue` `Grants` `Sync` |

规则：

- 右栏 tab 是页面级配置，不允许所有页面强行复用 `Assets / System / Runs`。
- 每个 tab 必须映射到独立 selector 和空态。
- 右栏切换不得重置中心画布的会话状态。

## 7. Agent Goal UI 设计

`Agent Goal` 是 `agent-first` 交互的核心组件，至少包含以下元素：

- `Goal Header`
  - 标题
  - 状态 badge：`draft|running|paused|blocked|completed|failed|cancelled`
  - 风险级别
  - 发起来源：`chat|ui|desktop|api`
- `Goal Step Rail`
  - step 列表
  - 当前 step 高亮
  - 成功/失败/等待态
  - 百分比或已完成计数
- `Thinking Card`
  - 摘要文本
  - reasoning 标签：`thinking|observing|planning|waiting`
  - 证据引用或工具选择依据
- `Tool Action Card`
  - 当前即将调用或正在调用的工具
  - 参数摘要
  - 风险/确认要求
- `Interrupt Controls`
  - `Pause`
  - `Resume`
  - `Cancel`
  - `Give Feedback`

渲染规则：

- `Agent Goal` 可作为 `ChatTimeline` 中的结构化消息卡出现，也可固定在 `Personal Workspace` 头部下方。
- `thinking` 和 `observing` 不应渲染为大段纯文本，应拆成折叠卡片和 bullet 摘要。
- `waiting_confirmation`、`waiting_approval`、`pending_merge` 必须显示为显式 blocker 卡，而不是普通消息。
- `Pause`、`Resume`、`Cancel`、`Feedback` 必须能关联到 `agent_goal_id` 和当前 `step_id`。

## 8. 组件清单

### 8.1 共享壳层组件

- `WorkspaceShell`
- `GlobalNav`
- `WorkspaceNav`
- `TopContextBar`
- `PageHeader`
- `RightPanelTabs`
- `ActionComposer`
- `ActivityInbox`

### 8.2 会话与 Agent 组件

- `ChatTimeline`
- `UserMessage`
- `AgentMessage`
- `StructuredMessageCard`
- `SuggestionChip`
- `GhostChip`
- `ToolPlanCard`
- `ToolProgressCard`
- `AgentGoalCard`
- `AgentStepRail`
- `ThinkingCard`
- `ObservationCard`
- `InterruptControls`

### 8.3 页面业务组件

- `ProjectCard`
- `VersionCard`
- `USBoard`
- `USCard`
- `QualityAssetLane`
- `AssetRevisionDiff`
- `RunCard`
- `RunTimeline`
- `FailureTimelineCard`
- `EvidenceCard`
- `ApprovalCard`
- `DiffViewer`
- `ReleaseReadinessPanel`
- `ProgressRing`
- `ConnectorHealthCard`
- `DesktopQueueCard`

### 8.4 右栏与 Inspector 组件

- `PanelSection`
- `EvidenceInspector`
- `SystemContextInspector`
- `PolicyInspector`
- `ImportInspector`
- `SyncInspector`

## 9. 交互模式

- `Welcome -> Build`
- `Welcome -> Dashboard`
- `Dashboard -> Project Overview`
- `Project Overview -> Version Space`
- `Version Space -> Personal Workspace`
- `Knowledge Gallery -> Knowledge Detail`
- `Runs -> Run Detail`
- `Governance -> Approval Detail`
- `Governance -> Release Readiness`

统一规则：

- 卡片上的主要 CTA 使用 `Open / Continue / Create / Review` 四类动词。
- 深层详情页必须提供返回父层的稳定入口，不依赖浏览器后退。
- 页面底部输入框 placeholder 必须随页面切换：
  - Build：`Ask Nasus to create a project, connect Git, or initialize a system image`
  - Dashboard：`Ask for portfolio progress, blockers, or risky projects`
  - Personal Workspace：`Generate, review, or revise quality assets for this US`
  - Runs：`Explain failures, retry execution, or inspect evidence`
  - Governance：`Resolve approvals, conflicts, and release gates`

## 10. 开发顺序建议

1. 固定 `WorkspaceShell`、`GlobalNav`、`WorkspaceNav`、`RightPanelTabs`
2. 先做 `Welcome`、`Build`、`Dashboard`
3. 再做 `Project Overview`、`Version Space`、`Personal Workspace`
4. 最后补 `Knowledge`、`Runs`、`Governance` 详情页
5. `Agent Goal UI` 与 `Personal Workspace` 同期落地，不后置
