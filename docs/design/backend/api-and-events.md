# Nasus 后端 API 与事件契约

## 1. 总体规则

- 写操作分两类：
  - `Conversation` 入口：主会话输入
  - `ToolInvocation` 入口：显式工具调用
- 读操作通过 read API 提供。
- 所有写操作都必须能回溯到 `tool_invocation_id` 或 `agent_goal_id`。
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
| `GET /v1/tool-invocations` | 按会话、AgentGoal、工具或状态查询工具调用链路 |
| `GET /v1/tool-invocations/{id}` | 获取工具调用状态与结果 |
| `POST /v1/tool-invocations/{id}/confirm` | 确认等待用户确认的工具调用 |
| `GET /v1/audit-events` | 查询会话、工具调用或 Agent Goal 的审计事件 |

### 2.2.1 Agent Goal

| 接口 | 用途 |
| --- | --- |
| `POST /v1/agent-goals` | 创建 Agent 自驱目标 |
| `GET /v1/agent-goals/{id}` | 获取目标详情 |
| `GET /v1/agent-goals/{id}/events` | 获取目标事件流 |
| `POST /v1/agent-goals/{id}/interrupt` | 打断目标执行 |
| `POST /v1/agent-goals/{id}/resume` | 恢复目标执行 |
| `POST /v1/agent-goals/{id}/feedback` | 向运行中的目标注入反馈 |

### 2.2.2 Agent Memory / Swarm

| 接口 | 用途 |
| --- | --- |
| `GET /v1/agent-memory/context` | 获取某次目标或会话的已组装记忆上下文摘要 |
| `POST /v1/agent-memory/checkpoints` | 创建会话或目标记忆 checkpoint |
| `GET /v1/agent-swarms/{id}` | 获取 Swarm 运行详情 |
| `POST /v1/agent-swarms` | 为复杂目标创建并行 Agent Swarm |
| `GET /v1/agent-swarms/{id}/events` | 获取 Swarm 事件流 |

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
| `POST /v1/retrieval/query` | 执行系统画像 hybrid retrieval，返回候选、rerank 和证据引用 |
| `GET /v1/retrieval-runs/{id}` | 获取检索运行记录 |
| `POST /v1/embeddings/rebuild` | 重建 stale 或指定范围 embedding |
| `POST /v1/rerank/test` | 测试 rerank provider 连接与返回格式 |
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

### 2.5 UCE / Connectors

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

### 2.6 MCP Server Management

| 接口 | 用途 |
| --- | --- |
| `GET /v1/mcp-servers` | 获取 MCP Server 列表 |
| `POST /v1/mcp-servers` | 注册 MCP Server |
| `PATCH /v1/mcp-servers/{id}` | 更新 MCP Server 配置 |
| `POST /v1/mcp-servers/{id}/health-check` | 手动健康检查 |
| `GET /v1/mcp-servers/{id}/health` | 获取健康状态 |

### 2.7 Notification / Activity

| 接口 | 用途 |
| --- | --- |
| `GET /v1/activity-inbox` | 获取跨页面待处理事项 |
| `PATCH /v1/activity-inbox/{id}/read` | 标记已读 |

### 2.8 Settings / Model Provider

| 接口 | 用途 |
| --- | --- |
| `GET /v1/settings` | 获取主题、语言、通知策略和三路模型配置状态 |
| `PATCH /v1/settings` | 更新主题、语言、通知策略或指定模型 route 配置 |
| `POST /v1/settings/test-connection` | 测试指定模型 route 的连接或 adapter 配置状态 |
| `GET /v1/settings/test-connection` | 返回连接测试接口的人类可读说明 |

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
  - 必要时的策略校验

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
- 审计要求：每次工具调用至少写入 `tool.invocation.created`，进入 gate 时写入 `tool.invocation.gated`，确认时写入 `tool.invocation.confirmed`，执行完成或失败时写入 `tool.invocation.completed / tool.invocation.failed`

`GET /v1/tool-invocations`

- 请求用途：为前端 `ToolInvocationTimeline`、AgentGoal 详情、审计排查和端到端追踪提供稳定查询入口。
- 至少支持过滤：
  - `conversation_id`
  - `agent_goal_id`
  - `tool_id`
  - `status`
- 返回顺序：按 `tool.invocation.created` 审计事件时间升序排列，表示 Agent 或用户实际触发工具的顺序。
- 约束：所有 UI 写动作、会话写动作和 Agent Loop 动作都必须能通过该接口回溯到同一个 `ToolInvocation` 事实对象。

`ToolResult` 最小字段：

- `status`
- `summary`
- `object_refs`
- `evidence_refs`
- `requires_followup`
- `followup_reason`
- `followup_prompt`
- `next_recommended_tools`

语义约束：

- `requires_followup=true` 表示工具当前动作已形成可审计结果，但后续 AgentGoal 需要等待用户或外部系统补齐输入。
- `followup_reason` 必须是可机读原因，例如 `missing_source_binding`。
- `followup_prompt` 用于前端和会话区展示下一步用户需要提供的信息。
- `ToolResult` 必须随 `ToolInvocation` 一起持久化，服务重启后 AgentGoal 恢复必须仍能读取 follow-up 状态。

`GET /v1/audit-events`

- 请求用途：查询正式审计事实，用于排查、治理、证据链展示和前端 Activity Timeline
- 至少支持过滤：
  - `conversation_id`
  - `tool_invocation_id`
  - `agent_goal_id`
- 返回对象必须包含：
  - `id`
  - `occurred_at`
  - `actor`
  - `actor_kind`
  - `action`
  - `entity_type`
  - `entity_id`
  - `status`
  - `summary`
  - `conversation_id`
  - `tool_invocation_id`
  - `agent_goal_id`
  - `object_refs`
  - `evidence_refs`
  - `metadata`
- 约束：`AuditEvent` 为 append-only 事实对象，不允许被软删或覆盖。

### 3.2.1 AgentGoal

`POST /v1/agent-goals`

- 请求用途：创建 Agent 自驱目标
- 同步返回：`agent_goal_id`、初始 `status`
- 异步行为：通过事件流回传 step、thinking、tool progress、pause/resume/completed
- 幂等：按 `client_goal_id` 或 `idempotency_key` 去重

### 3.2.2 Agent Memory / Swarm

`GET /v1/agent-memory/context`

- 请求用途：调试和前端展示本次 Agent 推理使用了哪些记忆与对象引用
- 至少支持：
  - `conversation_id`
  - `agent_goal_id`
  - `space_ref`
- 返回必须区分：
  - `working_memory`
  - `conversation_memory`
  - `project_long_term_memory`
  - `candidate_memory`
- 返回必须包含 `context_hash`、`context_summary`、`recent_turn_count`、`checkpoint_count` 和可见 `tool_catalog` 摘要。
- 安全约束：该接口只返回可解释摘要和对象引用，不返回完整 system prompt、完整 LLM prompt、API key、模型密钥或未裁剪的长上下文 dump。
- 系统画像场景下，`project_long_term_memory` 至少暴露 `system_image_status`、`baseline_refs`、`source_refs`、`context_object_refs` 和 `metric_groups`，用于解释 Agent 为什么选择继续 source binding、ingestion、context materialization 或 baseline initialization。

`POST /v1/agent-memory/checkpoints`

- 请求用途：显式创建会话或 AgentGoal 级 summary checkpoint，用于长对话压缩、断点恢复和 MemoryContextPanel 手动保存当前上下文。
- 至少支持：
  - `conversation_id`
  - `agent_goal_id`
  - `space_ref`
  - `created_by=system|user`
- 同步返回：`ConversationSummaryCheckpoint`
- 行为约束：
  - 若存在新的 completed text messages，则创建新的 checkpoint 并更新 `ConversationSession.latest_summary_checkpoint_id`。
  - 若没有新消息但已有 checkpoint，则返回最新 checkpoint，避免重复制造记忆噪声。
  - 若目标会话没有任何可 checkpoint 的 completed text message，则返回 `validation_error`。
- 事件要求：成功创建新 checkpoint 时发送 `agent.memory.checkpointed`，前端据此更新会话详情和 MemoryContextPanel。

`POST /v1/agent-swarms`

- 请求用途：由 Agent Service 为复杂目标创建并行子 Agent 任务
- 必须携带：
  - `parent_goal_id`
  - `swarm_kind`
  - `target_refs`
  - `max_parallel_agents`
  - `budget_ref`
  - `merge_strategy`
- 同步返回：`swarm_run_id`、初始 `status`
- 异步行为：通过事件流回传 assignment 创建、运行、完成、合并和失败事件
- 约束：不能由普通前端按钮绕过 Agent Service 直接创建无父目标的 swarm

`GET /v1/agent-swarms/{id}/events`

- 请求用途：订阅单个 `AgentSwarmRun` 的事件流，供 `SwarmRunPanel` 展示并行子 Agent 的创建、运行、合并和完成过程。
- 连接成功后必须先发送 `agent.swarm.snapshot`，其中 `payload.agent_swarm` 是当前完整 swarm read model。
- snapshot 之后继续发送实时事件：`agent.swarm.started / assignment_created / assignment_completed / merging / completed / failed`。
- 约束：该事件流是只读观测面，不允许前端通过事件接口恢复、重试或修改 assignment。

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
- `POST /v1/retrieval/query`
  - 用于系统画像和 Agent 记忆的统一检索入口。
  - 请求字段：
    - `project_id`
    - `version_id` 可空
    - `baseline_id` 可空
    - `query`
    - `query_intent=impact_analysis|similar_us|test_reuse|failure_analysis|release_evidence|general_context`
    - `filters`
    - `keyword_top_k`
    - `vector_top_k`
    - `graph_depth`
    - `rerank_top_k`
  - 响应字段：
    - `retrieval_run_id`
    - `strategy`
    - `keyword_candidates`
    - `vector_candidates`
    - `graph_candidates`
    - `merged_candidates`
    - `reranked_candidates`
    - `fallback_used`
    - `fallback_reason`
    - `evidence_refs`
  - 约束：
    - 必须先应用 project/version/baseline/RBAC 过滤，再做召回。
    - rerank 不可用时必须返回 `fallback_used=true` 和 rule-based fusion 结果。
    - 响应中的每个候选必须带 `source_refs`、`object_refs`、`score`、`rank_reason`。
- `GET /v1/retrieval-runs/{id}`
  - 返回 `RetrievalRun`、候选数量、rerank 状态、fallback 状态和最终结果引用。
- `POST /v1/embeddings/rebuild`
  - 请求字段：
    - `project_id`
    - `version_id` 可空
    - `target_type` 可空
    - `target_ids` 可空
    - `reason=model_changed|content_hash_changed|manual|failed_retry`
  - 响应字段：
    - `job_id`
    - `scheduled_count`
    - `skipped_count`
- `POST /v1/rerank/test`
  - 用于设置页和运维检查。
  - 请求字段：
    - `provider_profile_id`
    - `sample_query`
    - `sample_candidates`
  - 响应字段：
    - `status=live|fallback|failed`
    - `latency_ms`
    - `sample_ranked_candidates`
    - `error` 可空
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

### 3.6 Settings / Model Provider

`GET /v1/settings`

- 返回用途：给 Settings popover 和运行时状态展示提供配置 read model。
- 必须返回：
  - `language`
  - `theme`
  - `notification_mode`
  - `model_profiles`
  - legacy chat mirror 字段：`model_preset / model_provider / model_name / runtime_mode / custom_model`
- `model_profiles` 固定包含：
  - `chat`
  - `embedding`
  - `rerank`
- 每个 profile 必须包含：
  - `route`
  - `model_preset=system_default|custom`
  - `model_provider`
  - `model_name`
  - `runtime_mode=live|fallback`
  - `active_provider_status`
  - `custom_model`
- 响应不得返回明文 API key；只能返回 `has_api_key` 和 `api_key_masked`。
- 顶层 legacy 字段只代表 `chat` route，用于兼容现有主会话和测试链路，不代表 embedding 或 rerank。

`PATCH /v1/settings`

- 请求用途：更新全局 UI 设置或某一条模型 route。
- 模型配置请求字段：
  - `model_route=chat|embedding|rerank`，缺省为 `chat`
  - `model_preset=system_default|custom`
  - `custom_provider_kind=openai_compatible|openai|gemini|anthropic`
  - `custom_base_url`
  - `custom_model_name`
  - `custom_api_key`
- 约束：
  - API key 是 write-only 字段，后端必须加密持久化。
  - 未传 `custom_api_key` 时不得清除已保存 key；传空字符串表示清空该 route key。
  - 更新 `chat` route 后，主会话和 Agent Loop 立即按新配置生成后续消息。
  - 更新 `embedding` route 后，系统画像必须能识别 embedding 模型版本变化，并将相关 embedding 标记为 `stale` 或进入重建计划。
  - 更新 `rerank` route 后，后续 `RetrievalRun` 必须记录新的 rerank provider/model。
- 返回完整 `StudioSettings` read model。

`POST /v1/settings/test-connection`

- 请求用途：对某一条模型 route 做连接测试。
- 请求字段同 `PATCH /v1/settings` 的模型配置字段；未传字段时使用已保存配置。
- 响应字段：
  - `ok`
  - `model_route`
  - `provider`
  - `model_name`
  - `runtime_mode`
  - `fallback_provider`
  - `latency_ms`
  - `message`
- 语义：
  - `chat` route 必须真实调用目标模型的轻量 prompt。
  - `embedding` route 必须优先通过 embedding adapter 做轻量向量化探测；若 adapter 不支持，则返回配置级状态并在 `message` 中说明。
  - `rerank` route 必须优先通过 rerank adapter 做样例重排探测；若 provider 没有统一接口，则返回配置级状态并把真实探测记录到后续 retrieval job。
  - 测试失败不得修改已保存配置。

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
- `agent_goal_id`
- `agent_step_id`
- `swarm_run_id`
- `assignment_id`
- `task_id`
- `run_id`
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
- `agent.memory.context_built`
- `agent.memory.checkpointed`
- `agent.swarm.snapshot`
- `agent.swarm.started`
- `agent.swarm.assignment_created`
- `agent.swarm.assignment_completed`
- `agent.swarm.merging`
- `agent.swarm.completed`
- `agent.swarm.failed`
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
- `notification.created`
- `notification.read`

### 5.3 SSE 消费约束

- 事件必须可被前端 `EventReducer` 直接消费，后端不能只发“请刷新”的弱通知。
- `mutation_kind=patch` 时，`payload` 必须是可直接合并的增量补丁。
- `conversation.message.created` 必须提供 `payload.message`，前端可直接 append 到消息流。
- `agent.goal.updated` 必须提供 `payload.agent_goal`，前端可直接 upsert 到当前会话的 `agent_goals`。
- `tool.invocation.updated` 必须提供 `payload.tool_invocation`，前端可直接更新工具执行卡片或进度时间线。
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
- `agent.memory.context_built`
- `embedding.created`
- `embedding.stale`
- `embedding.rebuilt`
- `retrieval.run.created`
- `retrieval.run.completed`
- `rerank.completed`
- `rerank.fallback`
- `agent.swarm.started`
- `agent.swarm.completed`
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
- `state_conflict`
- `internal_error`

其中：

- `confirmation_required` 和 `approval_required` 不应被当作普通失败，而是 gate 状态。
- `conflict_state` 用于对象状态非法迁移和 `pending_merge` 阻塞。
