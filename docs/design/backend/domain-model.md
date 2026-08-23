# Nasus 后端领域模型

## 1. 目标

本文定义 Nasus 后端的 canonical domain model、对象关系、正式事实边界和核心状态机，作为 PostgreSQL schema 与领域服务实现的直接依据。

## 2. 对象分组

### 2.1 身份、认证与访问对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `UserIdentity` | `user_id`, `email`, `display_name`, `status`, `idp_subject`, `last_login_at` | 是 | 中心端 |
| `ProjectMembership` | `membership_id`, `project_id`, `user_id`, `role`, `status` | 是 | 中心端 |
| `RoleBinding` | `binding_id`, `project_id`, `version_id`, `session_id`, `user_id`, `role`, `scope_ref`, `effective_policy_ref` | 是 | 中心端 |
| `AccessSession` | `access_session_id`, `user_id`, `client_type`, `status`, `refresh_token_family_id`, `expires_at` | 是 | 中心端 |
| `ServicePrincipal` | `principal_id`, `service_name`, `status`, `scope_set`, `credential_ref` | 是 | 中心端 |

### 2.2 治理与空间对象

`Session.space_type` 与 `ConversationSession.space_type` 的 canonical 枚举固定为：

- `build`
- `dashboard`
- `project`
- `version`
- `workspace`
- `knowledge`
- `runs`
- `governance`
- `documentation`

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `Project` | `project_id`, `name`, `slug`, `status`, `owner_id`, `policy_profile_id` | 是 | 中心端 |
| `Version` | `version_id`, `project_id`, `name`, `status`, `source_baseline_id`, `git_branch_ref` | 是 | 中心端 |
| `Session` | `session_id`, `project_id`, `version_id`, `status`, `owner_id`, `space_type` | 是 | 中心端 |
| `ConversationSession` | `conversation_id`, `session_id`, `space_type`, `space_id`, `initiator_id`, `status`, `last_message_at` | 是 | 中心端 |
| `ConversationMessage` | `message_id`, `conversation_id`, `role`, `status`, `content_type`, `tool_refs`, `object_refs` | 是 | 中心端 |
| `ConversationSummaryCheckpoint` | `checkpoint_id`, `conversation_id`, `message_range_start`, `message_range_end`, `summary_text` | 是 | 中心端 |
| `ConversationLink` | `link_id`, `left_conversation_id`, `right_conversation_id`, `link_kind`, `confidence` | 是 | 中心端 |
| `SessionKnowledgeBinding` | `binding_id`, `conversation_id`, `candidate_object_ref`, `scope` | 是 | 中心端 |
| `USWorkItem` | `us_id`, `version_id`, `title`, `description_ref`, `assignee_id`, `status`, `risk_level` | 是 | 中心端 |
| `Baseline` | `baseline_id`, `project_id`, `kind`, `status`, `source_version_id`, `parent_baseline_id`, `fork_strategy`, `overlay_ref`, `materialized_snapshot_ref` | 是 | 中心端 |
| `CandidateKnowledge` | `candidate_id`, `project_id`, `version_id`, `source_object_refs`, `status`, `approval_state` | 否 | 中心端 |

### 2.3 对话、工具与编排对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `ToolDefinition` | `tool_id`, `tool_kind`, `scope`, `risk_level`, `confirmation_mode`, `input_schema_ref`, `output_schema_ref` | 是 | 中心端 |
| `ToolInvocation` | `invocation_id`, `conversation_id`, `tool_id`, `initiator_surface`, `initiator_actor`, `target_scope`, `status` | 是 | 中心端 |
| `ToolResult` | `invocation_id`, `status`, `summary`, `object_refs`, `evidence_refs`, `next_recommended_tools` | 否 | 中心端 |
| `AgentGoal` | `goal_id`, `conversation_id`, `status`, `autonomy_level`, `max_steps`, `steps_completed`, `workflow_id` | 是 | 中心端 |
| `AgentStep` | `step_id`, `goal_id`, `step_index`, `phase`, `decision`, `selected_tool_id`, `tool_invocation_id`, `memory_context_hash`, `available_tool_ids` | 是 | 中心端 |
| `AgentMemoryItem` | `memory_id`, `memory_scope`, `owner_ref`, `source_refs`, `summary`, `object_refs`, `expires_at` | 是 | 中心端 |
| `AgentMemoryLink` | `link_id`, `memory_id`, `target_ref`, `link_kind`, `confidence` | 是 | 中心端 |
| `AgentSwarmRun` | `swarm_run_id`, `parent_goal_id`, `conversation_id`, `swarm_kind`, `status`, `max_parallel_agents`, `budget_ref`, `merge_strategy` | 是 | 中心端 |
| `AgentWorkerAssignment` | `assignment_id`, `swarm_run_id`, `worker_agent_kind`, `target_refs`, `status`, `tool_invocation_refs`, `candidate_result_ref`, `timeout_seconds` | 是 | 中心端 |
| `SkillDefinition` | `skill_id`, `scope`, `mapped_tool_ids`, `internal_only` | 是 | 中心端 |
| `WorkerJob` | `job_id`, `skill_id`, `task_id`, `status`, `retry_count`, `queue_name` | 否 | 中心端 |

### 2.4 任务、上下文与结论对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `Task` | `task_id`, `project_id`, `version_id`, `us_id`, `status`, `current_resolution_id`, `max_healing_depth`, `healing_budget_used` | 是 | 中心端 |
| `TaskContext` | `task_context_id`, `task_id`, `status`, `related_feature_refs`, `evidence_refs` | 是 | 中心端 |
| `QualityProfile` | `quality_profile_id`, `task_context_id`, `status`, `risk_rating`, `verification_strategy` | 是 | 中心端 |
| `QualityAssetPack` | `asset_pack_id`, `us_id`, `version_id`, `status`, `scenario_set_ref`, `coverage_scope_ref`, `verification_plan_ref`, `case_set_ref`, `automation_asset_ref`, `performance_asset_ref`, `change_doc_ref`, `summary_ref`, `current_revision` | 是 | 中心端 |
| `AgentDecision` | `decision_id`, `task_id`, `source`, `decision_kind`, `status`, `confidence`, `evidence_refs` | 否 | 中心端 |
| `MergedResolution` | `resolution_id`, `task_id`, `resolution_kind`, `status`, `merged_from`, `approval_state` | 是 | 中心端 |
| `ApprovalRecord` | `approval_id`, `approval_kind`, `target_object_ref`, `status`, `approver_id`, `notes` | 是 | 中心端 |
| `ReleaseReadiness` | `version_id`, `status`, `score`, `blockers`, `approvals_open`, `pending_merge`, `score_breakdown`, `evidence_summary`, `blocker_items` | 是 | 中心端 |
| `ReleaseDecision` | `decision_id`, `project_id`, `version_id`, `status`, `score`, `rationale`, `evidence_refs`, `approval_ref` | 是 | 中心端 |

### 2.5 执行对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `Run` | `run_id`, `task_id`, `execution_channel`, `status`, `environment_ref`, `evidence_refs`, `healing_depth`, `cooldown_until`, `last_failure_fingerprint` | 是 | 中心端 |
| `ExecutionEvidence` | `evidence_id`, `run_id`, `kind`, `storage_ref`, `hash`, `captured_at` | 是 | 中心端 |
| `FailureReport` | `failure_id`, `run_id`, `failure_kind`, `summary`, `evidence_refs`, `failure_fingerprint`, `healing_attempt_count` | 是 | 中心端 |

### 2.6 知识与审计对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `ContextObject` | `object_id`, `type`, `status`, `confidence`, `source_refs`, `relationship_refs` | 是 | 中心端 |
| `ContextRelationship` | `relationship_id`, `from_object_id`, `relationship_type`, `to_object_id`, `baseline_id`, `confidence`, `source_refs` | 是 | 中心端 |
| `ContextObjectOverlay` | `overlay_id`, `baseline_id`, `object_id`, `field_path`, `operation`, `value_ref`, `source_refs` | 是 | 中心端 |
| `QualityMetricSnapshot` | `metric_snapshot_id`, `project_id`, `baseline_id`, `version_id`, `us_id`, `task_id`, `metric_group`, `metrics_ref` | 是 | 中心端 |
| `RawAssetRecord` | `raw_asset_id`, `project_id`, `version_id`, `source_type`, `canonical_uri`, `content_ref`, `content_hash`, `file_count`, `byte_count` | 是 | 中心端 |
| `RawAssetChunk` | `chunk_id`, `raw_asset_id`, `source_type`, `chunk_kind`, `content_ref`, `content_hash`, `section_path`, `token_estimate`, `metadata`, `embedding_record_id` | 是 | 中心端 |
| `EmbeddingRecord` | `embedding_id`, `source_ref`, `object_ref`, `chunk_ref`, `project_id`, `baseline_id`, `embedding_model`, `embedding_dimension`, `embedding_version`, `content_hash`, `vector_ref`, `status` | 是 | 中心端 |
| `RetrievalRun` | `retrieval_run_id`, `project_id`, `version_id`, `baseline_id`, `query_ref`, `query_intent`, `retrieval_strategy`, `candidate_count`, `rerank_status`, `result_refs` | 是 | 中心端 |
| `RerankRecord` | `rerank_id`, `retrieval_run_id`, `rerank_model`, `rerank_version`, `input_count`, `output_count`, `status`, `latency_ms`, `fallback_reason` | 是 | 中心端 |
| `ConnectorDefinition` | `connector_id`, `connector_type`, `status`, `config_ref` | 是 | 中心端 |
| `ConnectorBinding` | `binding_id`, `project_id`, `connector_id`, `status`, `scope_ref` | 是 | 中心端 |
| `ConnectorRun` | `run_id`, `binding_id`, `trigger_kind`, `status`, `checkpoint_ref` | 是 | 中心端 |
| `ConnectorCheckpoint` | `checkpoint_id`, `binding_id`, `cursor_ref`, `captured_at` | 是 | 中心端 |
| `MCPServerDefinition` | `server_id`, `name`, `transport_kind`, `status`, `endpoint_or_command_ref` | 是 | 中心端 |
| `MCPServerBinding` | `binding_id`, `project_id`, `server_id`, `status`, `policy_profile_id` | 是 | 中心端 |
| `MCPServerHealth` | `health_id`, `server_id`, `status`, `checked_at`, `details_ref` | 是 | 中心端 |
| `PolicySnapshot` | `policy_snapshot_id`, `scope`, `version`, `rules_ref` | 是 | 中心端 |
| `AuditEvent` | `event_id`, `occurred_at`, `actor`, `actor_kind`, `action`, `entity_type`, `entity_id`, `status`, `conversation_id`, `tool_invocation_id`, `agent_goal_id`, `object_refs`, `evidence_refs`, `metadata` | 是 | 中心端 |

## 3. 正式事实边界

- `UserIdentity / ProjectMembership / RoleBinding / AccessSession / ServicePrincipal / Project / Version / Session / ConversationSession / ConversationMessage / ConversationSummaryCheckpoint / ConversationLink / SessionKnowledgeBinding / USWorkItem / Baseline / AgentGoal / AgentStep / AgentMemoryItem / AgentMemoryLink / AgentSwarmRun / AgentWorkerAssignment / Task / TaskContext / QualityProfile / QualityAssetPack / Run / ExecutionEvidence / MergedResolution / ApprovalRecord / ReleaseReadiness / ReleaseDecision / ContextObject / ContextRelationship / ContextObjectOverlay / QualityMetricSnapshot / RawAssetRecord / RawAssetChunk / EmbeddingRecord / RetrievalRun / RerankRecord / ConnectorDefinition / ConnectorBinding / ConnectorRun / ConnectorCheckpoint / MCPServerDefinition / MCPServerBinding / MCPServerHealth / PolicySnapshot / AuditEvent` 属于正式事实对象。
- `ToolResult / WorkerJob / AgentDecision / CandidateKnowledge` 属于候选或执行中间对象。
- `AgentDecision` 不能直接推进正式放行、正式知识晋级或正式基线回写。
- `ToolInvocation` 是正式命令记录，但不是正式业务结论。

## 4. 核心状态机

### 4.1 Task

`draft -> analyzing -> pending_merge -> ready_for_review -> executing -> ready_for_release -> completed`

迁移规则：
- 只能由工具调用或系统 workflow 推动。
- `pending_merge` 只能由中心端候选结论冲突或候选结构冲突触发。
- `completed` 仅在 `MergedResolution` 已批准且相关 `Run` 关闭后进入。
- `healing_budget_used` 超过 `max_healing_depth` 后，不得再次进入自动自愈链，必须转入人工处理。

### 4.2 ToolInvocation

`pending -> running -> waiting_confirmation / waiting_approval -> completed / failed / cancelled`

每次 `ToolInvocation` 生命周期变更必须追加 `AuditEvent`：

- `tool.invocation.created`
- `tool.invocation.gated`
- `tool.invocation.confirmed`
- `tool.invocation.executing`
- `tool.invocation.completed`
- `tool.invocation.failed`

`AuditEvent` 不参与状态覆盖，属于 append-only 事实流；前端、治理和排障链路通过 `conversation_id / tool_invocation_id / agent_goal_id` 过滤读取。

迁移规则：
- 高风险工具默认可进入 `waiting_confirmation` 或 `waiting_approval`。
- 只有 gate 通过后才能重新回到 `running`。
- `completed` 必须写出 `ToolResult` 和至少一个对象引用或结果摘要。

### 4.3 Run

`pending -> running -> succeeded / failed / retrying / pending_merge / closed`

迁移规则：
- `execution_channel` 在当前阶段固定为 `web_runner`。
- `pending_merge` 仅用于中心端执行结论冲突或执行结果与候选结论冲突。
- `closed` 只在 failure/healing/release 链条结束后进入。
- 每次自动修复重试都必须递增 `healing_depth`。
- 当 `healing_depth >= Task.max_healing_depth` 时，禁止再次自动触发 `healing.propose`。
- 若 `cooldown_until` 未到，不得因相同 `last_failure_fingerprint` 立即再次进入自动重试。

### 4.4 AgentDecision

`provisional -> merged -> approved / rejected`

迁移规则：
- `provisional` 仅由中心端写入。
- `merged` 仅由中心端 `Merge / Score` 写入。
- `approved / rejected` 仅由 `Approval Control` 写入。

### 4.5 MergedResolution

`pending_merge -> ready_for_approval -> approved / rejected`

迁移规则：
- `pending_merge` 由冲突检测触发。
- `ready_for_approval` 由 `Merge / Score` 完成候选合并后触发。
- `approved / rejected` 由审批链触发。

### 4.6 CandidateKnowledge

`pending_review -> version_shared -> official / rejected`

迁移规则：
- `version_shared` 必须经版本级审批。
- `official` 必须在版本收口后经正式审批。

### 4.7 AccessSession

`active -> rotated -> revoked / expired`

迁移规则：
- `active` 由 OIDC/OAuth 登录完成后创建。
- `rotated` 由 refresh token rotation 触发。
- `revoked / expired` 后不得再签发新 access token。

### 4.8 ConversationSession

`draft -> active -> idle -> archived`

分支：

- `active -> merged`
- `active -> closed`

迁移规则：

- 首条消息写入后进入 `active`
- 被并入其他会话后进入 `merged`
- 归档后默认不出现在常规列表

### 4.9 ConversationMessage

`accepted -> streaming -> completed`

分支：

- `streaming -> interrupted`
- `streaming -> failed`
- `completed -> archived`

迁移规则：

- 流式 assistant 消息必须显式收到完成事件才可进入 `completed`
- 已完成消息正文 append-only

### 4.10 AgentGoal

`pending -> running -> paused -> completed`

分支：

- `running -> failed`
- `running -> cancelled`
- `paused -> running`
- `paused -> cancelled`

迁移规则：

- `paused` 必须带 `pause_reason`
- `max_steps` 是 AgentGoal 的硬预算；当 `steps_completed >= max_steps` 时，运行时必须在下一次 Tool 调用前进入 `paused(pause_reason=budget_exhausted)`，不得继续创建新的 `ToolInvocation`。
- `created / started / paused / resumed / completed / failed / cancelled / budget_exhausted` 必须追加 `AuditEvent`，其中 `metadata` 至少包含 `workflow_id`、`autonomy_level`、`max_steps`、`steps_completed` 和 `pause_reason`。
- 生命周期审计只能由 AgentGoal 状态机的显式迁移产生，普通 step patch 或 read-model 更新不得被误记为 `started`、`resumed` 等生命周期事件。
- 同一 `ConversationSession` 同时只允许一个 `running` 的 `AgentGoal`

### 4.11 AgentMemoryItem

`active -> summarized -> expired / promoted`

迁移规则：

- `memory_scope` 固定为 `working | conversation | project_long_term | candidate`。
- `working` 记忆只能绑定一个 `AgentGoal`，目标完成后必须转为 `summarized` 或 `expired`。
- `conversation` 记忆来自 `ConversationSummaryCheckpoint`、用户反馈或工具结果摘要。
- `project_long_term` 记忆必须来自已批准的 `ContextObject / Baseline / Evidence`，不能由 Agent 直接写入。
- `candidate` 记忆必须带 `source_refs`、`evidence_refs`、`confidence` 和候选来源，晋级必须经过 `Merge/Score + Approval Control`。
- `promoted` 只能由审批链触发。

### 4.12 AgentSwarmRun

`pending -> running -> merging -> completed / partially_failed`

分支：

- `running -> failed`
- `running -> cancelled`
- `merging -> failed`

迁移规则：

- `AgentSwarmRun` 必须绑定一个 `parent_goal_id`。
- `running` 状态下可并发存在多个 `AgentWorkerAssignment`，并发数不得超过 `max_parallel_agents`。
- 所有 assignment 完成或达到预算阈值后进入 `merging`。
- 至少一个 assignment 成功且至少一个失败时，合并后的终态必须为 `partially_failed`，不得伪装为 `completed`。
- `completed` 只表示候选结果合并完成，不代表正式业务结论已批准。
- `partially_failed` 表示可用候选已经合并，但下游必须保留失败 assignment 和缺失证据提示。
- 取消 swarm 不回滚已完成工具调用和证据。

### 4.13 AgentWorkerAssignment

`pending -> running -> completed / failed / cancelled`

迁移规则：

- 每个 assignment 必须有明确 `worker_agent_kind`、`target_refs`、输入上下文和输出 schema。
- 每个 assignment 必须持久化 `timeout_seconds`；超时按 `failed` 记录并保留可审计原因。
- assignment 可以创建子 `AgentGoal` 或直接触发工具，但不得直接写正式领域对象。
- `completed` 必须写出 `candidate_result_ref`、置信度和关联 `tool_invocation_refs`。
- 失败的 assignment 可以重试，但必须受 swarm 级预算和 rate limit 控制。

### 4.14 QualityAssetPack

`draft -> building -> review_ready -> approved / superseded`

迁移规则：
- `draft` 由 `USWorkItem` 创建时初始化。
- `building` 由相关 `Task` 写入资产引用时触发。
- `review_ready` 表示该 US 当前资产包已具备审核条件。
- `approved` 仅在版本级或任务级审核完成后进入。
- `superseded` 表示被更高 revision 的资产包视图替代，但历史 revision 不删除。

## 5. Baseline Fork 存储策略

- `Baseline` 默认采用 `copy-on-write + delta overlay` 策略，不做版本创建时的全量深拷贝。
- 字段约束：
  - `parent_baseline_id`：指向 fork 来源
  - `fork_strategy`：固定首发为 `cow_delta`
  - `overlay_ref`：指向该版本相对父基线的增量对象集
  - `materialized_snapshot_ref`：可选的物化快照，用于加速读取与审批
- 读取规则：
  - 默认查询先读 `overlay`
  - overlay 未命中时回退父基线
  - 必要时按 `materialized_snapshot_ref` 命中缓存快照
- 写入规则：
  - 版本期间只写 `overlay`
  - 官方基线只在版本收口后通过审批写回
- 物化快照只作为读优化，不作为正式事实源

### 5.1 USWorkItem 与 Task / QualityAssetPack 关系

- `Official System Image` 是项目知识基线，不是业务 `Version`。系统画像可以在首个
  `Version` 创建前发现候选 US 事实，但这些事实进入交付质量流程后必须归属且仅归属
  一个 `Version`。
- `USWorkItem.version_id` 是进入交付质量流程后的必填归属。版本输入导入、参与人分配、
  风险初始化、任务启动和工作区查询都必须同时使用 `project_id + version_id` 作为边界。
- US 集合替换是版本级操作，只允许替换目标 `(project_id, version_id)` 下的记录，不得
  删除或覆盖同项目其他版本的 US。项目工作区默认只返回当前活动版本的 US。
- 兼容系统画像先于版本创建的场景时，首个质量动作创建 `Initial Quality Loop`，并将
  尚未版本化的 US 一次性迁入该版本。该规则只执行一次；后续新版本不得复制、重绑或
  隐式继承历史版本 US，必须通过显式版本输入导入建立新事实。
- `USWorkItem` 与 `Task` 固定为 `1:N`。
- 一个 `USWorkItem` 下可以并行存在多个 `Task`，典型包括：
  - 场景分析任务
  - 用例生成任务
  - 自动化执行任务
  - 性能任务
  - 变更文档任务
- `QualityAssetPack` 是 `USWorkItem` 级聚合对象，固定为 `USWorkItem 1:1 current pack`。
- 各 `Task` 产出的结构化质量资产写入或更新同一个 `QualityAssetPack` 的不同部分，由 `current_revision` 追踪版本。
- `Task` 是过程对象，`QualityAssetPack` 是 US 级结果对象；两者不能互相替代。

### 5.2 QualityAssetPack 内部结构

- `scenario_set_ref`：测试场景集合
- `coverage_scope_ref`：测试范围与覆盖边界
- `verification_plan_ref`：验证计划、策略和环境要求
- `case_set_ref`：测试用例集合
- `automation_asset_ref`：自动化脚本与执行配置
- `performance_asset_ref`：性能脚本与性能验证说明
- `change_doc_ref`：变更文档、变更说明、影响摘要
- `summary_ref`：阶段总结、执行摘要、结论摘要
- `current_revision`：每次关键资产更新递增，用于审计和前端缓存一致性

## 6. 关键关系

- `Project 1:N Version`
- `Version 1:N USWorkItem`
- `Version 1:N Session`
- `Project 1:N ProjectMembership`
- `Project 1:N RoleBinding`
- `Session 1:N ConversationSession`
- `ConversationSession 1:N ConversationMessage`
- `ConversationSession 1:N ConversationSummaryCheckpoint`
- `ConversationSession 1:N SessionKnowledgeBinding`
- `ConversationSession 1:N AgentGoal`
- `USWorkItem 1:N Task`
- `USWorkItem 1:1 QualityAssetPack`
- `ConversationSession 1:N ToolInvocation`
- `AgentGoal 1:N AgentStep`
- `AgentGoal 1:N AgentMemoryItem(memory_scope=working)`
- `AgentGoal 1:N AgentSwarmRun`
- `AgentStep 0:1 ToolInvocation`
- `AgentMemoryItem 1:N AgentMemoryLink`
- `AgentSwarmRun 1:N AgentWorkerAssignment`
- `AgentWorkerAssignment 0:1 AgentGoal`
- `AgentWorkerAssignment 0:N ToolInvocation`
- `Task 1:1 TaskContext`
- `Task 1:1 QualityProfile`
- `Task 1:N Run`
- `Task 1:N AgentDecision`
- `Task 1:N MergedResolution`
- `Run 1:N ExecutionEvidence`
- `Project 1:N RawAssetRecord`
- `RawAssetRecord 1:N RawAssetChunk`
- `ContextObject 1:N ContextRelationship(from)`
- `ContextObject 1:N ContextRelationship(to)`
- `Baseline 1:N ContextObjectOverlay`
- `Project 1:N QualityMetricSnapshot`
- `Version 1:N QualityMetricSnapshot`
- `USWorkItem 1:N QualityMetricSnapshot`
- `Task 1:N QualityMetricSnapshot`
- `Project 1:N ConnectorBinding`
- `ConnectorDefinition 1:N ConnectorBinding`
- `ConnectorBinding 1:N ConnectorRun`
- `ConnectorBinding 1:N ConnectorCheckpoint`
- `Project 1:N MCPServerBinding`
- `MCPServerDefinition 1:N MCPServerBinding`

## 7. 实现约束

- 所有正式对象必须包含 `created_at / updated_at / created_by / updated_by / version` 审计字段。
- 所有正式对象必须支持外部稳定 ID，不暴露数据库自增主键。
- 软删只允许用于管理对象，不允许用于 `Run / Evidence / AuditEvent / ApprovalRecord`。
- `AuditEvent` 和 `ExecutionEvidence` 必须 append-only。
- 所有对象变更都必须能关联回 `tool_invocation_id`。
- `Baseline` 的 overlay 对象必须支持按 `object_id + field_path` 精确查询，以便合并查询和再基线化。
- `ContextRelationship` 必须支持 baseline-aware traversal，查询时遵循 `overlay first, parent fallback`。
- `QualityMetricSnapshot` 必须能区分 `code_quality / us_completion_quality / test_quality / release_readiness` 四类指标组。
- 代码、历史 US、历史测试用例和脚本必须作为一等 `source_type` 支持：
  - `git_repository`
  - `historical_us_document`
  - `historical_test_case`
  - `automation_script`
  - `test_asset_bundle`

## 8. ContextObject 类型体系

### 8.1 `type` 枚举

- `system`
- `module`
- `service`
- `component`
- `page`
- `flow`
- `api`
- `schema`
- `requirement`
- `us`
- `quality_asset_pack`
- `test_scenario`
- `test_case`
- `automation_asset`
- `performance_asset`
- `risk_pattern`
- `execution_evidence`
- `external_dependency`

### 8.2 `relationship_type` 枚举

- `contains`
- `implements`
- `depends_on`
- `calls`
- `exposes`
- `verifies`
- `impacts`
- `allocated_to`
- `derived_from`
- `evidenced_by`
- `belongs_to_branch`
- `supersedes`

### 8.3 图谱查询要求

- `ContextObject` 必须支持按：
  - `type`
  - `relationship_type`
  - `project_id / version_id / baseline_id`
  - `source_ref`
  - `status`
  组合查询
- 图谱查询返回必须支持：
  - root object
  - neighbor edges
  - typed path summary
  - pagination / depth limit
- 图谱查询接口的正式契约见后端 API 文档。

## 8.4 Embedding / Retrieval / Rerank 要求

V1 必须把 embedding、hybrid retrieval 和 rerank 作为系统画像正式检索链路的一部分落地。

### 8.4.1 `EmbeddingRecord`

状态机：

`pending -> ready -> stale -> ready`  
`pending -> failed`  
`pending -> excluded`

V1 降级状态：

- 当 `model_profiles.embedding` 未配置为 live，系统仍必须为可检索 source/object 生成 `EmbeddingRecord(status=fallback)`，并记录本地 hash vector ref、fallback reason、embedding model/version。
- fallback embedding 只能作为可审计降级投影，不能被描述为外部 embedding provider 已完成。

规则：

- `content_hash` 变化后，相关 embedding 必须进入 `stale`。
- 不同 `embedding_model / embedding_version / embedding_dimension` 的向量不能混排。
- `excluded` 只能用于二进制、空内容、不可解析内容或策略排除内容，并必须记录 `exclude_reason`。
- embedding 是检索投影，不是正式业务事实；正式事实仍来自 `ContextObject / ContextRelationship / Baseline / Evidence`。

### 8.4.2 `RetrievalRun`

每次 UCE 检索必须记录：

- query intent
- keyword topK
- vector topK
- graph expansion depth
- filter snapshot
- candidate merge 策略
- rerank 状态
- 最终 result refs

这保证 `TaskContext / QualityProfile / AgentMemoryContext` 可以解释“为什么召回这些知识”。

### 8.4.3 `RerankRecord`

状态机：

`pending -> completed / failed / fallback`

规则：

- rerank provider 不可用时必须回退 rule-based fusion，不得阻断系统画像构建。
- fallback 必须记录 `fallback_reason`、`provider_status` 和 `AuditEvent`。
- LLM 只能用于 query rewrite、候选解释或小批量辅助判断；不能替代权限过滤、baseline 过滤和 source/evidence 约束。
