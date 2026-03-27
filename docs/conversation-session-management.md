# Nasus 会话与消息管理设计

## 1. 文档定位

本文补齐 `ConversationSession`、消息对象、会话级知识隔离、上下文窗口管理与多会话协作设计，作为主会话、Agent Loop、SSE Streaming 和前端会话工作台的实现基线。

优先级关系：

- 产品交互与默认规则以 [docs/final-feature-spec.md](/Users/uben/project/project/Nasus/docs/final-feature-spec.md) 为准。
- 主会话如何产出 `ToolInvocationPlan` 以 [docs/conversation-orchestrator-design.md](/Users/uben/project/project/Nasus/docs/conversation-orchestrator-design.md) 为准。
- Agent 自主循环协议以 [docs/agent-loop-runtime.md](/Users/uben/project/project/Nasus/docs/agent-loop-runtime.md) 为准。
- 本文定义会话和消息的持久化对象、状态机、API 与上下文管理。

## 2. 设计目标

- 会话是 Agent-first 产品的主交互容器，而不是临时聊天记录。
- 消息是可审计、可回放、可搜索、可绑定工具与对象的正式事实对象。
- Agent 的 `thinking -> acting -> observing -> deciding` 必须能稳定映射为会话内的结构化消息与流式块。
- 长会话必须支持摘要、裁剪、检索和恢复，不依赖“把全部历史塞给模型”。
- `Session-only Knowledge` 必须和工作会话绑定，不能脱离会话孤立存在。

## 3. 核心对象

### 3.1 ConversationSession

最小字段：

- `conversation_id`
- `session_id`
- `space_type=build|dashboard|project|version|workspace|knowledge|runs|governance|documentation`
- `space_id`
- `project_id`
- `version_id` 可空
- `us_id` 可空
- `task_id` 可空
- `initiator_id`
- `title`
- `status`
- `last_message_at`
- `latest_summary_checkpoint_id` 可空
- `merged_into_conversation_id` 可空
- `archived_at` 可空

### 3.2 ConversationMessage

最小字段：

- `message_id`
- `conversation_id`
- `role=user|assistant|system|tool`
- `status=accepted|streaming|completed|interrupted|failed|archived`
- `content_type=text|markdown|structured_card|tool_progress|thinking|image_ref|file_ref|diff_ref|approval_card|conflict_card|evidence_ref`
- `content_blocks`
- `tool_refs`
- `object_refs`
- `metadata`
- `stream_id` 可空
- `sequence_max` 可空
- `created_at`

说明：

- `content_blocks` 采用 JSONB 数组，块级别 append-only。
- 大附件、截图、trace、图片等不内嵌正文，只在 block 中保存 `storage_ref`。

### 3.3 ConversationSummaryCheckpoint

最小字段：

- `checkpoint_id`
- `conversation_id`
- `message_range_start`
- `message_range_end`
- `summary_text`
- `summary_object_refs`
- `summary_token_count`
- `created_by=system|user`
- `created_at`

### 3.4 ConversationLink

用于“自动提示相关会话”“会话合并”“跨会话检索”。

最小字段：

- `link_id`
- `left_conversation_id`
- `right_conversation_id`
- `link_kind=related|duplicate|merged_from|derived_from`
- `reason`
- `confidence`
- `created_at`

### 3.5 SessionKnowledgeBinding

用于把 `Session-only Knowledge` 显式绑定到会话。

最小字段：

- `binding_id`
- `conversation_id`
- `candidate_object_ref`
- `scope=session_only`
- `created_at`

## 4. 会话状态机

### 4.1 ConversationSession

`draft -> active -> idle -> archived`

分支：

- `active -> merged`
- `active -> closed`
- `idle -> active`

迁移规则：

- `draft` 仅用于刚创建、尚未写入第一条消息的会话。
- 写入首条消息后转为 `active`。
- 超过阈值时间无活动可转 `idle`，再次写消息恢复 `active`。
- `archived` 表示不再出现在默认列表，但保留搜索与审计能力。
- `merged` 表示被并入另一会话，必须记录 `merged_into_conversation_id`。
- `closed` 仅用于明确终止的系统会话或已完成的临时流程会话。

### 4.2 ConversationMessage

`accepted -> streaming -> completed`

分支：

- `streaming -> interrupted`
- `streaming -> failed`
- `completed -> archived`

迁移规则：

- 用户消息通常直接 `accepted -> completed`。
- Assistant 流式消息先进入 `streaming`，收到 `assistant.message.completed` 后转 `completed`。
- 断流进入 `interrupted`，允许后续恢复流式续写。
- 已完成消息正文默认不可变，修正以追加 block 或新消息表示。

## 5. 存储设计

### 5.1 PostgreSQL 表建议

- `conversation_sessions`
- `conversation_messages`
- `conversation_summary_checkpoints`
- `conversation_links`
- `session_knowledge_bindings`
- `conversation_search_index`

### 5.2 字段与存储策略

- `conversation_messages.content_blocks`：JSONB，适合多类型 block 与流式拼接。
- `metadata`：JSONB，只存 UI/追踪相关元数据，不存大正文副本。
- 大附件正文、trace、图片、长 diff：写入 MinIO，仅在 block 中保存 `storage_ref + hash + content_type`。
- 检索字段：
  - `title`
  - 最近摘要
  - 角色文本拼接后的 `tsvector`
  - `project_id / version_id / session_id / task_id`

## 6. API 设计

### 6.1 会话管理

- `POST /v1/conversations`
  - 创建会话
- `GET /v1/conversations`
  - 列表，支持按 `project_id/version_id/session_id/space_type/status` 过滤
- `GET /v1/conversations/{id}`
  - 返回会话详情与统计
- `PATCH /v1/conversations/{id}/archive`
  - 归档会话
- `POST /v1/conversations/{id}/merge`
  - 合并到目标会话
- `GET /v1/conversations/search`
  - 搜索会话、消息命中和 related sessions

### 6.2 消息读写

- `POST /v1/conversations/{id}/messages`
  - 写入用户消息或结构化指令
- `GET /v1/conversations/{id}/messages`
  - 支持分页和 `before_message_id`
- `GET /v1/conversations/{id}/events`
  - SSE streaming 与工具进度流

## 7. 上下文窗口管理

### 7.1 裁剪原则

- 默认不把完整消息历史直接发给模型。
- 会话输入给 LLM 前，优先组装：
  - 最新 N 条消息
  - 最近一个或多个 `ConversationSummaryCheckpoint`
  - 当前空间的 `visible_context_refs`
  - 当前未完成工具和待处理审批摘要

### 7.2 Checkpoint 策略

- 每累计一定 token 或消息数，自动生成 checkpoint。
- 用户显式要求“总结当前进展”时，也生成 checkpoint。
- checkpoint 只总结已完成消息区间，不覆盖活跃流式消息。

### 7.3 Pinned Context

会话允许 pin 关键上下文：

- `project brief`
- `version brief`
- `current us`
- `active task`
- `latest quality profile`
- `open blockers`

Pinned 内容优先进入 LLM context packaging。

## 8. Agent Loop 与消息映射

| Agent Loop 阶段 | 会话内表现 |
| --- | --- |
| `thinking` | `assistant` 消息，`content_type=thinking` 或 `structured_card` |
| `acting` | `tool` 消息或 `tool_progress` block，关联 `tool_invocation_id` |
| `observing` | `assistant` 消息，输出观察摘要和 evidence refs |
| `deciding` | `assistant` 消息，输出下一步、暂停原因或完成总结 |

规则：

- Agent 的每个 step 至少关联一条消息或 block。
- 不对外暴露未审计的内部 scratchpad；可展示的是可追溯、可审计的 reasoning 摘要。
- `tool_refs` 必须能把消息反向定位到 `ToolInvocation`。

## 9. 多会话协作

### 9.1 相关会话推荐

系统基于以下信号生成 `ConversationLink`：

- 相同 `project_id / version_id / us_id`
- 命中相同 `Task / Run / Approval / ContextObject`
- 相似问题摘要
- 共享 `CandidateKnowledge`

### 9.2 会话合并

仅允许把“同空间、同项目、语义高度相近”的会话合并。

合并结果：

- 原会话保留，状态转 `merged`
- 新会话保留完整消息链
- `ConversationLink(link_kind=merged_from)` 写入

## 10. Session-only Knowledge 绑定规则

- 会话内新增的候选知识默认写成 `CandidateKnowledge + SessionKnowledgeBinding`。
- 只有进入版本共享或官方基线时，才脱离单会话约束。
- 会话归档不删除 session-only knowledge，但默认不再进入新会话上下文，除非显式引用或被推荐。

## 11. 实现默认值

- 会话与消息默认存 PostgreSQL。
- `content_blocks` 和 `metadata` 采用 JSONB。
- 大附件正文走 MinIO，正文只保留 `storage_ref`。
- `assistant` 流式输出首发固定走 SSE。
- 搜索首发基于 PostgreSQL 全文检索；后续如有需要可接专门索引层，但 canonical 数据仍在 PostgreSQL。
