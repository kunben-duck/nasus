# Nasus 后端 API 与事件契约

## 1. 总体规则

- 写操作分两类：
  - `Conversation` 入口：主会话输入
  - `ToolInvocation` 入口：显式工具调用
- 读操作通过 read API 提供。
- 所有写操作都必须能回溯到 `tool_invocation_id`。
- 所有异步写操作都必须提供 SSE 事件流。

## 2. REST 接口分组

### 2.1 Auth / Access

| 接口 | 用途 |
| --- | --- |
| `GET /v1/auth/me` | 获取当前身份、角色和会话范围 |
| `POST /v1/auth/device-code` | CLI / Device Code 登录 |
| `POST /v1/auth/token` | token 交换 |
| `POST /v1/auth/refresh` | refresh token rotation |
| `POST /v1/auth/logout` | 注销当前访问会话 |

### 2.2 Conversation / Tool

| 接口 | 用途 |
| --- | --- |
| `POST /v1/conversations` | 创建会话 |
| `GET /v1/conversations` | 获取会话列表 |
| `GET /v1/conversations/{id}` | 获取会话详情 |
| `GET /v1/conversations/search` | 搜索会话与消息 |
| `PATCH /v1/conversations/{id}/archive` | 归档会话 |
| `POST /v1/conversations/{id}/merge` | 合并会话 |
| `POST /v1/conversations/{id}/messages` | 主会话输入入口 |
| `GET /v1/conversations/{id}/events` | 会话事件流 |
| `GET /v1/tools/catalog` | 获取工具目录 |
| `POST /v1/tool-invocations` | 显式工具调用 |
| `GET /v1/tool-invocations/{id}` | 获取工具调用状态与结果 |

### 2.2.1 Agent Goal

| 接口 | 用途 |
| --- | --- |
| `POST /v1/agent-goals` | 创建 Agent 自驱目标 |
| `GET /v1/agent-goals/{id}` | 获取目标详情 |
| `GET /v1/agent-goals/{id}/events` | 获取目标事件流 |
| `POST /v1/agent-goals/{id}/interrupt` | 打断目标执行 |
| `POST /v1/agent-goals/{id}/resume` | 恢复目标执行 |
| `POST /v1/agent-goals/{id}/feedback` | 向运行中的目标注入反馈 |

### 2.3 Domain Read / Write Boundary

| 接口 | 用途 |
| --- | --- |
| `POST /v1/projects` | 创建项目对象 |
| `POST /v1/versions` | 创建版本对象 |
| `POST /v1/sessions` | 创建工作会话 |
| `POST /v1/tasks` | 显式创建任务对象 |
| `GET /v1/tasks/{id}` | 获取任务详情 |
| `GET /v1/tasks/{id}/events` | 获取任务事件流 |
| `GET /v1/tasks/{id}/conflicts` | 获取任务冲突 |
| `GET /v1/context-objects/{id}` | 获取上下文对象详情 |
| `GET /v1/context-objects/search` | 搜索上下文对象 |
| `GET /v1/context-graph` | 图谱查询 |
| `GET /v1/features/{featureId}/context` | 获取对象/特性上下文 |
| `GET /v1/objects/{id}` | 获取对象详情 |

### 2.4 Execution / Governance

| 接口 | 用途 |
| --- | --- |
| `POST /v1/runs` | 创建执行 |
| `GET /v1/runs/{id}` | 获取执行详情 |
| `GET /v1/runs/{id}/events` | 执行事件流 |
| `POST /v1/approvals` | 发起审批 |
| `GET /v1/approvals/{id}/events` | 审批事件流 |

### 2.5 Device / Sync

| 接口 | 用途 |
| --- | --- |
| `POST /v1/devices/register` | 注册设备 |
| `POST /v1/device-sessions` | 打开设备会话 |
| `GET /v1/device-sessions/{id}/events` | 设备会话事件流 |
| `POST /v1/sync` | 同步增量状态与补传 |
| `GET /v1/sync/events` | 同步事件流 |
| `POST /v1/capabilities/negotiate` | 协商本地能力 |

### 2.6 UCE / Connectors

| 接口 | 用途 |
| --- | --- |
| `GET /v1/connectors` | 获取 connector 列表 |
| `POST /v1/connectors` | 创建 connector 定义或绑定 |
| `PATCH /v1/connectors/{id}` | 更新 connector 配置 |
| `POST /v1/connectors/{id}/runs` | 触发一次摄入 run |
| `GET /v1/connectors/{id}/runs` | 获取摄入 run 历史 |
| `GET /v1/raw-assets/{id}` | 获取原料详情 |
| `GET /v1/context-objects/{id}` | 获取上下文对象详情 |
| `GET /v1/context-objects/search` | 搜索上下文对象 |
| `GET /v1/context-graph` | 图谱查询 |

### 2.7 MCP Server Management

| 接口 | 用途 |
| --- | --- |
| `GET /v1/mcp-servers` | 获取 MCP Server 列表 |
| `POST /v1/mcp-servers` | 注册 MCP Server |
| `PATCH /v1/mcp-servers/{id}` | 更新 MCP Server 配置 |
| `POST /v1/mcp-servers/{id}/health-check` | 手动健康检查 |
| `GET /v1/mcp-servers/{id}/health` | 获取健康状态 |

### 2.8 Notification / Activity

| 接口 | 用途 |
| --- | --- |
| `GET /v1/activity-inbox` | 获取跨页面待处理事项 |
| `PATCH /v1/activity-inbox/{id}/read` | 标记已读 |

## 3. 接口语义规则

### 3.0 Auth / Access

- `GET /v1/auth/me` 必须返回：
  - `user`
  - `project_memberships`
  - `role_bindings`
  - `active_access_session`
- `POST /v1/auth/refresh` 必须执行 refresh token rotation，旧 refresh token 立即失效。
- 所有写接口默认都需要通过：
  - `AuthMiddleware`
  - `AccessMiddleware`
  - 必要时的 `CapabilityGrant` 校验

### 3.1 Conversation

`POST /v1/conversations`

- 请求用途：创建新会话
- 最小字段：
  - `session_id`
  - `space_type`
  - `space_id`
  - `title` 可空

`GET /v1/conversations`

- 返回用途：按空间和项目列出会话
- 至少支持：
  - `project_id`
  - `version_id`
  - `session_id`
  - `space_type`
  - `status`
  - `q`

`POST /v1/conversations/{id}/messages`

- 请求用途：提交自然语言输入或结构化指令
- 同步返回：消息接收确认、`conversation_id`
- 异步行为：通过事件流回传 `tool_invocation_plan`、执行进度和结构化结果
- 幂等：按 `client_message_id` 去重

`PATCH /v1/conversations/{id}/archive`

- 请求用途：归档会话
- 约束：归档不删除消息，不影响审计和搜索

`POST /v1/conversations/{id}/merge`

- 请求用途：把当前会话并入目标会话
- 约束：必须返回 `target_conversation_id` 与 `ConversationLink`

### 3.2 ToolInvocation

`POST /v1/tool-invocations`

- 请求用途：直接触发工具调用
- 同步返回：`tool_invocation_id`、初始 `status`
- 异步行为：通过事件流推进到 `running / waiting_confirmation / waiting_approval / completed / failed`
- 幂等：按 `idempotency_key` 去重

### 3.2.1 AgentGoal

`POST /v1/agent-goals`

- 请求用途：创建 Agent 自驱目标
- 同步返回：`agent_goal_id`、初始 `status`
- 异步行为：通过事件流回传 step、thinking、tool progress、pause/resume/completed
- 幂等：按 `client_goal_id` 或 `idempotency_key` 去重

### 3.3 Read API

- `GET` 类接口只返回 read model
- 不负责推进长流程
- 不允许隐式修改正式状态

### 3.4 Conflict Read Model

`GET /v1/tasks/{id}/conflicts`

- 返回用途：给前端 `Conflict Panel` 和治理页面展示结构化冲突
- 最小返回字段：
  - `task_id`
  - `conflict_state`
  - `object_ref`
  - `base_ref`
  - `left_candidate_ref`
  - `right_candidate_ref`
  - `auto_merged_patch`
  - `conflict_entries`
  - `recommended_resolution`
- `conflict_entries` 的最小字段：
  - `path`
  - `conflict_kind=scalar|object|array|text`
  - `base_value`
  - `left_value`
  - `right_value`
  - `merge_hint`
  - `requires_manual_resolution`
- 前端不得自己推断 3-way merge；后端必须直接返回可渲染的冲突 payload。

### 3.5 Context Graph Read Model

- `GET /v1/context-objects/{id}`
  - 返回单个 `ContextObject` 的标准详情、关系摘要和证据摘要
- `GET /v1/context-objects/search`
  - 至少支持：
    - `type`
    - `status`
    - `project_id`
    - `version_id`
    - `baseline_id`
    - `q`
- `GET /v1/context-graph`
  - 至少支持：
    - `root_id`
    - `depth`
    - `node_types`
    - `relationship_types`
    - `baseline_id`
  - 返回：
    - `nodes`
    - `edges`
    - `path_summaries`
    - `page_info`

## 4. 统一响应约定

所有同步响应至少包含：

- `request_id`
- `timestamp`
- `status`
- `data`

所有异步对象至少包含：

- `id`
- `status`
- `correlation_id`
- `conversation_id`
- `tool_invocation_id`
- `entity_version`

统一错误响应固定为：

```json
{
  "request_id": "string",
  "timestamp": "ISO8601",
  "error": {
    "code": "string",
    "message": "string",
    "details": {},
    "retry_after": null
  }
}
```

## 5. SSE 事件流

### 5.1 统一事件信封

所有 SSE 事件至少包含：

- `event_id`
- `event_type`
- `occurred_at`
- `correlation_id`
- `conversation_id`
- `tool_invocation_id`
- `task_id`
- `run_id`
- `device_session_id`
- `entity_type`
- `entity_id`
- `entity_version`
- `mutation_kind=replace|patch|append|invalidate`
- `query_keys`
- `snapshot_hint`
- `payload`

### 5.2 公开事件类型

- `conversation.message.created`
- `conversation.archived`
- `conversation.merged`
- `conversation.plan.updated`
- `conversation.agent_goal.proposed`
- `agent.goal.created`
- `agent.goal.updated`
- `agent.goal.paused`
- `agent.goal.resumed`
- `agent.goal.completed`
- `agent.goal.failed`
- `agent.step.thinking`
- `agent.step.acting`
- `agent.step.observing`
- `agent.step.decided`
- `tool.invoked`
- `tool.waiting_confirmation`
- `tool.waiting_approval`
- `tool.completed`
- `tool.failed`
- `task.updated`
- `run.started`
- `run.updated`
- `run.completed`
- `conflict.detected`
- `resolution.merged`
- `approval.requested`
- `approval.completed`
- `device.heartbeat`
- `sync.applied`
- `notification.created`
- `notification.read`

### 5.3 SSE 消费约束

- 事件必须可被前端 `EventReducer` 直接消费，后端不能只发“请刷新”的弱通知。
- `mutation_kind=patch` 时，`payload` 必须是可直接合并的增量补丁。
- `mutation_kind=invalidate` 时，必须显式给出 `query_keys`，禁止让前端自行猜测失效范围。
- 若单次变更过大、存在版本跳跃或补丁不可逆，后端应设置 `snapshot_hint=true`，指示前端对单对象做精确 refetch。

### 5.4 Conversation Streaming 协议

首发对话流式输出固定采用 SSE，不额外引入自定义双向流协议。

`GET /v1/conversations/{id}/events` 必须支持以下事件序列：

- `assistant.message.started`
- `assistant.message.delta`
- `assistant.message.completed`
- `assistant.block.updated`
- `tool.invoked`
- `tool.progress`
- `tool.completed`
- `tool.failed`

流式事件最小字段：

- `stream_id`
- `message_id`
- `sequence`
- `chunk_index`
- `is_final`
- `content_type=text|markdown|structured_block|tool_progress`

约束：

- 同一 `message_id` 下的 `assistant.message.delta` 必须严格递增 `sequence`
- `assistant.message.completed` 是该消息唯一的结束信号
- 结构化卡片、计划卡、工具进度卡不得通过纯文本 delta 模拟，必须走 `assistant.block.updated`
- `tool.progress` 必须包含：
  - `tool_invocation_id`
  - `step_label`
  - `progress_percent`
  - `status_text`
- 前端遇到断流时，不得把未完成消息直接视为完成，必须保留 `stream_interrupted` 状态并允许重连后续接

## 6. 内部 Domain Events

内部事件至少包括：

- `project.created`
- `version.created`
- `session.created`
- `task.created`
- `task.context_built`
- `quality_profile_built`
- `worker.started`
- `worker.completed`
- `agent_decision.created`
- `candidate_knowledge.promoted`
- `baseline.promoted`

## 7. 错误语义

错误码至少分为：

- `validation_error`
- `permission_denied`
- `policy_blocked`
- `confirmation_required`
- `approval_required`
- `not_found`
- `conflict_state`
- `retry_later`
- `integration_error`
- `sync_conflict`
- `internal_error`

其中：

- `confirmation_required` 和 `approval_required` 不应被当作普通失败，而是 gate 状态。
- `conflict_state` 用于对象状态非法迁移和 `pending_merge` 阻塞。
