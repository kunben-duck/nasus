# Nasus 会话运行时设计

## 1. 文档定位

本文合并原“Conversation Orchestrator 设计”和“会话与消息管理设计”，统一定义：

- 主会话如何把自然语言输入变成 `ClarificationRequest / DirectAnswer / ToolInvocationPlan / AgentGoalProposal`
- 会话、消息、摘要、会话级知识绑定的持久化模型
- 会话上下文窗口、SSE streaming、多会话协作和 Agent Loop 映射
- 会话记忆如何进入 `Agent Memory Manager`

优先级关系：

- 产品行为与默认规则以 [最终特性说明书](../../final-feature-spec.md) 为准。
- Agent 自主循环协议以 [./agent-loop-runtime.md](./agent-loop-runtime.md) 为准。
- 工具目录以 [./tool-catalog.md](./tool-catalog.md) 为准。
- 工具执行协议以 [../backend/runtime-and-tool-protocol.md](../backend/runtime-and-tool-protocol.md) 为准。

## 2. 设计目标

- 会话是 Agent-first 产品的主交互容器，而不是临时聊天记录。
- 消息是可审计、可回放、可搜索、可绑定工具与对象的正式事实对象。
- 会话输入优先产出结构化执行结果，而不是自由文本聊天。
- 长会话必须支持摘要、裁剪、恢复和跨会话关联。
- `Session-only Knowledge` 必须和会话绑定，不能直接污染版本共享或官方基线。
- 会话记忆是 Agent Service 的正式输入，不能只作为前端聊天历史存在。

## 3. Conversation Orchestrator 职责

`Conversation Orchestrator` 只做 4 件事：

- 理解用户输入
- 绑定当前空间上下文
- 生成计划或高级目标
- 判断是否需要澄清、确认或直接回答

它不直接：

- 改正式领域状态
- 绕过工具层执行
- 长时间等待审批或执行完成

## 4. 输入与输出

### 4.1 最小输入上下文

- `conversation_id`
- `space_type`
- `space_id`
- `project_id`
- `version_id` 可空
- `session_id` 可空
- `us_id` 可空
- `task_id` 可空
- `latest_messages`
- `visible_context_refs`
- `actor_ref`
- `role_set`

### 4.2 固定输出类型

`Conversation Orchestrator` 只允许输出 4 类结果之一：

- `ClarificationRequest`
- `DirectAnswer`
- `ToolInvocationPlan`
- `AgentGoalProposal`

规则：

- 只要请求能落到现有工具目录，就优先产出 `ToolInvocationPlan` 或 `AgentGoalProposal`
- 缺少关键上下文或高风险决策信息不足时，先产出 `ClarificationRequest`
- 高级目标、需要持续自主推进的请求，必须产出 `AgentGoalProposal`

## 5. 处理流程

### 5.1 五阶段管线

1. `Normalize`
2. `Bind Context`
3. `Classify Intent`
4. `Plan Action`
5. `Emit`

### 5.2 决策原则

- 查询型、低风险、无需工作流推进的请求可产出 `DirectAnswer`
- 只读查询型的单步或多步确定性动作可产出 `ToolInvocationPlan`
- 需要持续推进的高层目标产出 `AgentGoalProposal`
- 结构化 Planner 产出的计划只要包含任意写工具，就必须在执行前提升为
  `AgentGoalProposal`；不得把多步写计划作为不可中断的同步请求直接执行
- 高风险治理动作可以被规划，但必须在计划中标注 `waiting_confirmation / waiting_approval`

### 5.3 与 Agent Loop / Tool Runtime 的边界

- `Conversation Orchestrator` 解决“接下来做什么”
- `Agent Memory Manager` 解决“本次思考应该带入哪些短期、会话和长期记忆”
- `Tool Invocation Runtime` 解决“如何统一执行这个动作”
- `Agent Loop Runtime` 解决“如何围绕一个高层目标持续推进”
- `LangGraph` 解决“单个工具或单次 goal step 内部如何思考和路由 Skill”

### 5.4 结构化 Planner 的治理边界

`LLM Structured Planner` 可以读取当前角色和空间可见的完整 `Tool Catalog`，
但模型输出是不可信候选计划。进入执行层前必须经过 `AgentPlanPolicy`：

- 只接受 Tool Catalog 中已经注册的 `tool_id`
- 每个计划最多包含 12 个工具动作
- 单个工具输入最大 32 KiB，且必须是可序列化 JSON
- 禁止模型写入幂等键、审批状态、确认状态、策略快照等运行时保留字段
- `conversation_id / project_id / version_id / us_id / task_id` 以当前会话绑定为准；
  模型提供的冲突 ID 必须被拒绝，而不是覆盖会话作用域
- 校验工具的 `scope` 和 `required_context`
- 禁止同一计划中出现工具、作用域和输入完全相同的重复动作
- `quality_loop` 和 `us.quality.complete` 目标必须以 `release.assess` 收尾，
  防止 Agent 在未评估放行条件时宣称闭环完成

如果校验发现缺少上下文、作用域冲突、计划超预算或闭环不完整，
Orchestrator 必须返回 `ClarificationRequest`。高风险工具允许进入候选计划，
但真正执行时仍由 `ToolInvocationRuntime` 的 confirmation / approval / policy gate
决定是否挂起。

## 6. 会话核心对象

### 6.1 ConversationSession

最小字段：

- `conversation_id`
- `session_id`
- `space_type=welcome|build|dashboard|documentation|project|version|workspace|knowledge|runs|governance|release_readiness`
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

### 6.2 ConversationMessage

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

### 6.3 ConversationSummaryCheckpoint

- `checkpoint_id`
- `conversation_id`
- `message_range_start`
- `message_range_end`
- `summary_text`
- `summary_object_refs`
- `summary_token_count`
- `created_by=system|user`
- `created_at`

说明：

- `ConversationSummaryCheckpoint` 是会话记忆的主要事实源。
- Agent Service 组装上下文窗口时，必须优先通过 `Agent Memory Manager` 读取 checkpoint 和最近消息。
- checkpoint 只代表会话级记忆，不自动晋级为项目长期记忆。

### 6.4 ConversationLink

- `link_id`
- `left_conversation_id`
- `right_conversation_id`
- `link_kind=related|duplicate|merged_from|derived_from`
- `reason`
- `confidence`
- `created_at`

### 6.5 SessionKnowledgeBinding

- `binding_id`
- `conversation_id`
- `candidate_object_ref`
- `scope=session_only`
- `created_at`

## 7. 会话与消息状态机

### 7.1 ConversationSession

`draft -> active -> idle -> archived`

分支：

- `active -> merged`
- `active -> closed`
- `idle -> active`

### 7.2 ConversationMessage

`accepted -> streaming -> completed`

分支：

- `streaming -> interrupted`
- `streaming -> failed`
- `completed -> archived`

规则：

- 用户消息通常直接 `accepted -> completed`
- assistant 流式消息走 `streaming`
- 已完成消息正文 append-only，不做原地覆盖

## 8. 存储与搜索

### 8.1 PostgreSQL 表

- `conversation_sessions`
- `conversation_messages`
- `conversation_summary_checkpoints`
- `conversation_links`
- `session_knowledge_bindings`
- `conversation_search_index`

### 8.2 存储策略

- `content_blocks`、`metadata` 使用 JSONB
- 大附件正文、trace、图片、长 diff 存 MinIO，仅在消息块中记录 `storage_ref`
- 会话搜索首发基于 PostgreSQL 全文检索

## 9. API 与事件

### 9.1 会话管理

- `POST /v1/conversations`
- `GET /v1/conversations`
- `GET /v1/conversations/{id}`
- `PATCH /v1/conversations/{id}/archive`
- `POST /v1/conversations/{id}/merge`
- `GET /v1/conversations/search`

### 9.2 消息读写

- `POST /v1/conversations/{id}/messages`
- `GET /v1/conversations/{id}/messages`
- `GET /v1/conversations/{id}/events`

### 9.3 关键事件

- `conversation.message.created`
- `conversation.plan.updated`
- `conversation.agent_goal.proposed`
- `conversation.archived`
- `conversation.merged`

## 10. 上下文窗口管理

### 10.1 输入打包原则

默认不把完整会话历史直接发给模型，优先组装：

- 最新 N 条消息
- 最近一个或多个 `ConversationSummaryCheckpoint`
- 当前空间的 `visible_context_refs`
- 当前未完成工具、待处理审批和 blocker 摘要

### 10.2 Checkpoint 策略

- 每累计一定消息数或 token 数，自动生成 checkpoint
- 用户显式要求“总结当前进展”时，也生成 checkpoint
- 只总结已完成消息区间，不覆盖活跃流式消息

### 10.3 Pinned Context

会话允许 pin：

- `project brief`
- `version brief`
- `current us`
- `active task`
- `latest quality profile`
- `open blockers`

## 11. Agent Loop 与消息映射

| Agent Loop 阶段 | 会话内表现 |
| --- | --- |
| `thinking` | `assistant` 消息，`content_type=thinking` 或 `structured_card` |
| `acting` | `tool` 消息或 `tool_progress` block |
| `observing` | `assistant` 消息，输出观察摘要和 evidence refs |
| `deciding` | `assistant` 消息，输出下一步、暂停原因或完成总结 |

规则：

- 每个 `AgentStep` 至少关联一条消息或 block
- 不对外暴露未审计的 scratchpad，只展示可追溯的 reasoning 摘要
- `tool_refs` 必须能反向定位到 `ToolInvocation`

## 12. 多会话协作

### 12.1 相关会话推荐

系统可基于以下信号生成 `ConversationLink`：

- 相同 `project_id / version_id / us_id`
- 命中相同 `Task / Run / Approval / ContextObject`
- 相似问题摘要
- 共享 `CandidateKnowledge`

### 12.2 会话合并

仅允许把“同空间、同项目、语义高度相近”的会话合并：

- 原会话保留，状态转 `merged`
- 目标会话保留完整消息链
- 写入 `ConversationLink(link_kind=merged_from)`

## 13. Session-only Knowledge 规则

- 会话内新增候选知识默认写成 `CandidateKnowledge + SessionKnowledgeBinding`
- 只有进入 `Version Shared` 或 `Official Baseline` 时才脱离单会话约束
- 会话归档不删除 session-only knowledge，但默认不进入新会话上下文，除非显式引用

## 14. 实现默认值

- 会话与消息默认存 PostgreSQL
- `assistant` 流式输出首发固定走 SSE
- 搜索首发基于 PostgreSQL 全文检索
- 主会话优先走 `Conversation Orchestrator -> ToolInvocationPlan / AgentGoalProposal` 主线
