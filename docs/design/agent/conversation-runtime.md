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
- `LangGraph` 解决“单次 Conversation Turn、单个工具或单次 goal step 内部如何规划和路由”
- `Temporal` 是 Turn 和 AgentGoal 进程生命周期、重试、取消的唯一权威
- `ToolInvocationRuntime` 仍是所有正式动作的唯一命令面，LangGraph 节点不得绕过它

Temporal 将 `ConversationTurn` 与 `AgentGoal` 投递到独立 Task Queue。Turn Activity
可以委派并等待 AgentGoal，而不会占满 AgentGoal 的 Activity 并发槽。默认队列分别为
`{NASUS_TEMPORAL_TASK_QUEUE}-conversation-turns` 与
`NASUS_TEMPORAL_TASK_QUEUE`，前者可通过
`NASUS_TEMPORAL_CONVERSATION_TURN_TASK_QUEUE` 显式覆盖。

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

### 6.3 ConversationTurn

最小字段：

- `turn_id`
- `conversation_id`
- `user_message_id`
- `assistant_message_id` 可空
- `workflow_id` 可空
- `idempotency_key`
- `status=accepted|planning|streaming|delegated|completed|interrupted|failed`
- `result`
- `error` 可空
- `created_at / updated_at / completed_at`

同一会话最多存在一个非终态 Turn；数据库通过活动状态部分唯一索引兜底。

### 6.4 ConversationSummaryCheckpoint

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

- `ConversationSummaryCheckpoint` 是可重建的压缩视图，不是任务状态或授权的事实源。
- Agent Service 组装上下文窗口时，必须优先通过 `Agent Memory Manager` 读取 checkpoint 和最近消息。
- checkpoint 只代表会话级记忆，不自动晋级为项目长期记忆。

### 6.5 ConversationLink

- `link_id`
- `left_conversation_id`
- `right_conversation_id`
- `link_kind=related|duplicate|merged_from|derived_from`
- `reason`
- `confidence`
- `created_at`

### 6.6 SessionKnowledgeBinding

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
- `conversation_turns`
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

- `POST /v1/conversations/{id}/messages`：保存用户消息和 Turn 后立即返回 `202 Accepted`
- `GET /v1/conversations/{id}/messages`
- `GET /v1/conversations/{id}/events`
- `GET /v1/conversations/{id}/turns/{turn_id}`
- `POST /v1/conversations/{id}/turns/{turn_id}/cancel`

消息 POST 必须接收 `Idempotency-Key`；重复请求返回同一个 Turn，不重复执行。

### 9.3 关键事件

- `conversation.message.created`
- `conversation.turn.accepted`
- `conversation.message.started`
- `conversation.message.delta`
- `conversation.message.completed`
- `conversation.message.interrupted`
- `conversation.message.failed`
- `conversation.turn.completed|interrupted|failed`
- `conversation.plan.updated`
- `conversation.agent_goal.proposed`
- `conversation.archived`
- `conversation.merged`

## 10. 上下文窗口管理

### 10.1 输入打包原则

`NASUS_CONVERSATION_MEMORY_V2=true` 时，按 token 预算组装系统规则、当前输入、
实时任务事实、结构化任务笔记、累计摘要、未覆盖原文与相关证据。当前输入只发送一次，
近期消息保留 user/assistant 原生角色。默认输入上限 16384，70% 持久化整理任务，
90% 在模型发送前检查并等待必要压缩。未知 tokenizer 使用明确标记的 UTF-8 字节保守估算，
不是字符数除以 4；已识别的 OpenAI 模型使用 tiktoken。

后台压缩保留最近 4 个完整轮次和当前未完成轮次。摘要不能覆盖或删除原文；失败后保留
上一份有效摘要及全部未覆盖消息，关键内容仍超限时显式失败，不静默丢掉用户约束。
`NASUS_MEMORY_MODEL_BUDGETS` 可按模型设置 input_limit、context_window、output_reserve、
safety_reserve；配置窗口时须给模型输出和协议开销留足空间。

### 10.2 Checkpoint 策略

- 模型输入为上一份有效摘要、未覆盖消息和有引用的工具观察，输出目标、约束、决策、问题、下一步、证据与不确定项。
- 每项记录来源引用、user_statement / assistant_inference / tool_observation 与 active / superseded / uncertain 状态。
- 旧约束必须原样保留，可标记 superseded；新更正另附来源。确定性检查结构、引用、来源类别和约束遗漏。
- 摘要固定入队时的 chat 配置；切换模型或权限范围后旧任务不能提交。fallback/mock 不能冒充成功的语义摘要。
- `memory_payload` 保存格式版本 2、父摘要、覆盖范围、来源、模型绑定、用途、提示词版本、用量及耗时，兼容原 summary_text。
- 旧格式首次按需从原文分批重建，不将旧截断文本升级为可信语义记忆。

### 10.3 后台整理与权限

`conversation_memory_jobs` 是持久化投递意图。消息写入仅登记任务，不等待模型或 Temporal。
现有 Worker 每 3 秒调度至 `{NASUS_TEMPORAL_TASK_QUEUE}-conversation-memory` 队列，最多两个并发。
模型调用超时 60 秒，数据库 lease 90 秒，最多两次尝试；attempt fencing 与父摘要 CAS
阻止旧 Worker 覆盖新结果。重启后继续扫描未完成任务，已完成任务重复执行不再次调用模型。
摘要、会话指针和 `conversation.summary.updated` Outbox 事件在同一事务提交。
执行前及模型返回后重新读取账号状态、角色和会话权限，账号撤销后的结果不得提交。
后台任务要求真实的有效账号；无身份的内部调用或未持久化的开发模拟身份不能生成有效摘要。

任务笔记从有效摘要与现有 Build intake / AgentGoal 记录组装，不新增业务状态机。
项目、数据源、候选、发布、审批和执行状态仍以当前授权范围内的业务记录为准，
不增加劫持普通问题的全局路由。原文、摘要和回查结果每次使用重新检查访问权限；
缺少完整 source-local provenance 的受限历史整体隐藏，不用旧摘要绕过撤权。

`query.conversation.history.search` 和 `query.conversation.history.read` 通过 ToolInvocation 执行，
限定当前会话。首版为确定性关键词匹配与按消息 ID 分页回读，不声称已实现语义向量搜索。
工具输出保存引用并按权限回读，广播只携带引用，不广播历史正文。
`GET /v1/agent-memory/context` 增加覆盖范围、整理状态、预算及降级原因，检查本身不触发摘要；
手动 checkpoint 接口返回真实生成结果，模型失败则返回错误。

### 10.4 灰度与验收

新功能默认关闭；API 与 Worker 同时开启 `NASUS_CONVERSATION_MEMORY_V2`，并运行迁移
`0124_conversation_memory`。需要 Temporal Worker 才有后台整理；本地运行时只支持发送前
必要整理或手动 checkpoint，不承诺后台进度。关闭开关可回到旧上下文策略，原始消息不变。
本轮不新增跨会话自动记忆，也不引入新的 Agent 框架。

验收必须区分确定性 fixture 与真实模型：30 轮中文、跨 3 次压缩的 fixture 只证明链路及约束校验，
不能证明模型总结质量。真实模型回放与基线比较、首 token 延迟和成本测量通过前不得默认开启。
摘要用量通过 `agent.conversation_summary` 审计关联；未配置单价时成本未知，不记为零费用。

回归入口：`test_semantic_conversation_memory.py`、`test_conversation_summary_model.py`、
`test_conversation_memory_postgres.py`、`test_conversation_memory_api.py`，数据库测试使用
`scripts/test-api-postgres.py` 的一次性 PostgreSQL，禁止使用开发数据跑测试。

模型预算通过 `NASUS_MEMORY_MODEL_BUDGETS` 的模型名称键覆盖。每项支持 `input_limit`、
`context_window`、`output_reserve`、`safety_reserve` 和 `summary_output_tokens`（默认 4096）。
未知模型使用明确标注的 UTF-8 字节保守估算；配置窗口时，输入上限同时扣除输出预留与安全余量。
推理模型可能将输出额度用于思考，需针对实际模型调整摘要输出预算，不放宽 JSON 或来源校验。
可选 `input_usd_per_million` / `output_usd_per_million` 是运维提供的价格，绝不猜测实时模型价格。

显式运行真实模型回放：设置 `NASUS_MEMORY_LIVE_EVAL=true` 后运行
`test_conversation_memory_live.py`。它只使用虚构任务输入，但会调用当前 chat 模型并产生正常调用审计与费用。
本次 `deepseek-v4-flash` 在 `summary_output_tokens=8192`、`output_reserve=8192` 的单次回放中，
完成 30 轮 / 3 次压缩，关键检索锚点 4/4，旧摘要基线 0/4；三次耗时约 8.9 / 17.5 / 27.0 秒。
默认 4096 额度曾出现空结果或不完整 JSON，均被拒绝，原文未丢失。因此单次通过不等于所有模型已验收。

`test_conversation_memory_temporal.py` 使用显式 `TEST_TEMPORAL_ADDRESS` 与一次性 PostgreSQL，
验证提交后丢失确认、新 Worker 接力和工作流历史重放；模型采用确定性 fixture，不冒充真实模型评测。
浏览器诊断展示由 `tests/e2e/conversation-memory.spec.ts` 验证，接口响应为 UI 契约样本。
既有完整门禁仍有 Build intake 相关 API 断言、BuildComposer 行数阈值、旧语言切换标题断言及
smoke 的立即项目跳转预期未通过；未因本轮改造放宽这些测试。默认启用前还需解决这些回归差异，
补充多次真实续接稳定性和首 token 延迟对比。当前只记录延迟指标，不宣称已证明端到端延迟改善。

### 10.5 Pinned Context

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
- Turn 图固定为 `load_context -> plan -> route -> clarify|invoke_tool|start_goal|generate_reply -> finalize`
- 只有 `generate_reply` 节点输出 token delta；Planner、Embedding、Rerank 和结构化生成保持非流式
- Provider 事件通过基础设施防腐适配器转成 Nasus 事件，再进入 PostgreSQL Outbox
- 流式消息的 `started/delta/completed/interrupted/failed` 状态变更与对应 Outbox 事件由同一 SQLAlchemy Unit of Work 提交，事务成功后才唤醒进程内 SSE 队列
- Python 3.11+ 通过节点参数显式注入 LangGraph 原生 `StreamWriter` 并消费 `stream_mode="custom"`；Python 3.9 本地开发因 LangGraph 0.6 的异步 `ContextVar` 限制，在基础设施适配器内部使用兼容事件队列，公开事件契约与图节点保持一致
