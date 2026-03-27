# Nasus 前端应用架构

## 1. 文档定位

本文是前端工程架构文档，定义 Portal 与 Desktop 共用的目录结构、路由、状态管理分层、构建部署与测试策略。

优先级关系：

- 视觉与交互基线以 [ux/index.html](/Users/uben/project/project/Nasus/ux/index.html) 和 [docs/frontend-visual-style.md](/Users/uben/project/project/Nasus/docs/frontend-visual-style.md) 为准。
- 业务对象和接口以 [docs/frontend-backend-design.md](/Users/uben/project/project/Nasus/docs/frontend-backend-design.md) 为准。
- 本文定义前端工程实现方式。

## 2. 应用边界

前端分为两个应用：

- `apps/portal`
  - Web Portal
- `apps/desktop`
  - Desktop Client

共享包：

- `packages/ui`
- `packages/tokens`
- `packages/api-client`
- `packages/contracts`
- `packages/state`

## 3. 目录结构建议

```text
apps/
  portal/
    src/
      app/
      routes/
      features/
      pages/
      components/
      stores/
      reducers/
      hooks/
  desktop/
    src/
      app/
      routes/
      features/
      ipc/
      local-runtime/
packages/
  ui/
  tokens/
  api-client/
  contracts/
  state/
```

## 4. 路由结构

Portal 路由建议：

- `/`
- `/home`
- `/conversations`
- `/tasks/:taskId`
- `/knowledge`
- `/runs/:runId?`
- `/settings`
- `/approvals/:approvalId?`
- `/agent-goals/:goalId?`

Desktop 路由建议：

- `/`
- `/tasks/:taskId?`
- `/runs/:runId?`
- `/device`
- `/sync`
- `/settings`

## 5. 状态管理分层

状态固定拆为 4 层：

### 5.1 Server State

- 由 TanStack Query 管理
- 对象包括：
  - `ConversationSession`
  - `Conversation`
  - `AgentGoal`
  - `ToolInvocation`
  - `Task`
  - `Run`
  - `Approval`
  - `DeviceSession`
  - `ConnectorRun`
  - `MCPServerHealth`

### 5.2 Event State

- 由统一 `EventReducer` 管理
- 消费 SSE / Desktop 事件流
- 负责 patch、append、invalidate、version check

### 5.3 UI State

- 由 Zustand 或等价 store 管理
- 对象包括：
  - `activeNav`
  - `activeContextTab`
  - `composerState`
  - `selectedRunId`
  - `selectedObjectId`

### 5.4 Local Runtime State

- 仅 Desktop 使用
- 包括：
  - `deviceStatus`
  - `offlineQueue`
  - `pendingUploads`
  - `capabilityGrantState`

### 5.5 Streaming State

- 由 `MessageStreamAssembler` 负责组装对话流式输出
- 最小状态包括：
  - `streamId`
  - `messageId`
  - `sequence`
  - `draftContent`
  - `structuredBlocks`
  - `toolProgressMap`
  - `streamStatus=idle|streaming|interrupted|completed`

规则：

- `assistant.message.delta` 只追加到 `draftContent`
- `assistant.block.updated` 只更新结构化块，不得覆写整条消息正文
- `assistant.message.completed` 才能把 `draftContent` 提交为正式消息
- 断流时进入 `stream_interrupted`，保留已收到内容并允许重连

规则：

- Server State 不直接存 UI 展开状态
- UI State 不缓存后端正式对象快照
- 所有正式对象变更以 SSE/EventReducer 为准

## 6. 功能模块拆分

Portal / Desktop 至少按以下 feature 组织：

- `conversation`
- `conversation-management`
- `agent-goals`
- `tools`
- `tasks`
- `knowledge`
- `runs`
- `approvals`
- `settings`
- `connectors`
- `mcp-servers`
- `device`（desktop 必选）
- `sync`（desktop 必选）

每个 feature 至少包含：

- `api.ts`
- `queries.ts`
- `reducer.ts`
- `components/`
- `types.ts`

## 7. 组件边界

共享基础组件：

- `WorkspaceShell`
- `SidebarNav`
- `MainHeader`
- `ChatTimeline`
- `StructuredMessageCard`
- `ActionComposer`
- `RightPanelTabs`
- `StatusBadge`

业务组件：

- `ToolPalette`
- `ToolInvocationTimeline`
- `ConflictPanel`
- `EvidenceTimeline`
- `GovernancePanel`
- `DeviceStatusPanel`

规则：

- 基础组件不直接依赖具体业务对象
- 业务组件通过 `packages/contracts` 消费统一类型

## 8. API Client 与 Contracts

- 所有前端请求统一通过 `packages/api-client`
- 所有共享类型来自 `packages/contracts`
- 不允许在页面组件中手写 endpoint path 和 response type

## 9. 认证初始化与路由保护

- Portal 启动时先请求 `GET /v1/auth/me`
- 未认证用户只允许进入登录与回调路由
- 已认证用户再根据 `project_memberships + role_bindings` 决定可见导航
- Desktop 启动时先恢复本地受保护 session，再刷新 access token
- 所有受保护页面都必须通过路由守卫加载：
  - 认证态
  - 当前项目/版本选择态
  - 必要的角色范围

## 10. 错误处理 UI 规范

错误必须按来源分层展示，不允许统一 toast 一把梭：

- `field error`
  - 表单字段内提示
- `action error`
  - 按钮/工具调用附近的内联错误
- `panel error`
  - `Tasks` / `Runs` / `Knowledge` 局部面板错误
- `page banner`
  - 当前页面仍可继续操作，但核心信息不完整
- `blocking modal`
  - 确认失败、审批失败、高风险动作被阻断
- `fatal route error`
  - 页面级兜底错误边界

错误码到 UI 的最小映射：

- `validation_error` -> field / action error
- `permission_denied` -> blocking modal
- `policy_blocked` -> blocking modal + guidance
- `confirmation_required` -> confirmation drawer / modal
- `approval_required` -> approval waiting card
- `retry_later` -> action error + retry affordance
- `integration_error` -> panel error / page banner
- `sync_conflict` -> Desktop sync banner + conflict entry

## 11. 通知系统

通知系统首发不做复杂工作流，但要先定义两层：

- `ephemeral toast`
  - 成功、轻量失败、后台任务已开始
- `activity inbox`
  - 审批请求
  - 冲突待处理
  - 同步失败
  - 桌面端待确认动作

规则：

- toast 只用于短时反馈，不承载治理动作
- 需要跨页面处理的事项必须进入 `activity inbox`
- 通知必须能关联：
  - `conversation_id`
  - `tool_invocation_id`
  - `task_id`
  - `run_id`

## 12. Desktop IPC 设计

Electron 首发固定采用：

- `renderer`
- `preload`
- `main`
- `local-agent-runtime`

IPC 原则：

- renderer 不直接访问 Node API
- 所有跨进程调用都经 `preload` 白名单暴露
- `main` 只接受 schema 校验后的消息
- 本地高风险动作最终由 `local-agent-runtime` 执行，不在 renderer 或 main 内直接拼接命令

首发 IPC channel 分组：

- `auth:*`
- `device:*`
- `capability:*`
- `tool:*`
- `sync:*`
- `artifact:*`
- `notification:*`

## 13. 构建与部署

- `portal`
  - 使用现代 React 构建链
  - 产物部署到静态站点或前端容器
- `desktop`
  - Electron 打包
  - 前端 UI 和本地 runtime 分离进程

环境分层：

- `local`
- `dev`
- `staging`
- `prod`

每个环境必须支持独立：

- API base URL
- SSE endpoint
- auth config
- feature flags

## 14. 测试策略

前端测试至少分 4 层：

- 单元测试
  - reducer
  - hooks
  - state selectors
- 组件测试
  - `ToolPalette`
  - `ChatTimeline`
  - `ConflictPanel`
- 集成测试
  - query + event reducer + page rendering
- 端到端测试
  - Portal 关键主链路
  - Desktop 关键同步链路

## 15. 实现默认值

- 前端采用 monorepo 结构
- Portal 与 Desktop 共享设计 token、contracts 和基础组件
- 所有实时状态以 `TanStack Query + EventReducer` 为准
- `ux/` 目录是视觉和布局实现基线，不是一次性 demo
