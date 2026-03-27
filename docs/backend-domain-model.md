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
| `ConversationSession` | `conversation_id`, `session_id`, `space_type`, `space_id`, `initiator_id`, `status`, `last_message_at` | 是 | 中心端 / Desktop |
| `ConversationMessage` | `message_id`, `conversation_id`, `role`, `status`, `content_type`, `tool_refs`, `object_refs` | 是 | 中心端 / Desktop |
| `ConversationSummaryCheckpoint` | `checkpoint_id`, `conversation_id`, `message_range_start`, `message_range_end`, `summary_text` | 是 | 中心端 |
| `ConversationLink` | `link_id`, `left_conversation_id`, `right_conversation_id`, `link_kind`, `confidence` | 是 | 中心端 |
| `SessionKnowledgeBinding` | `binding_id`, `conversation_id`, `candidate_object_ref`, `scope` | 是 | 中心端 |
| `USWorkItem` | `us_id`, `version_id`, `title`, `description_ref`, `assignee_id`, `status`, `risk_level` | 是 | 中心端 |
| `Baseline` | `baseline_id`, `project_id`, `kind`, `status`, `source_version_id`, `parent_baseline_id`, `fork_strategy`, `overlay_ref`, `materialized_snapshot_ref` | 是 | 中心端 |
| `CandidateKnowledge` | `candidate_id`, `project_id`, `version_id`, `source_object_refs`, `status`, `approval_state` | 否 | 中心端 / Edge |

### 2.3 对话、工具与编排对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `ToolDefinition` | `tool_id`, `tool_kind`, `scope`, `risk_level`, `confirmation_mode`, `input_schema_ref`, `output_schema_ref` | 是 | 中心端 |
| `ToolInvocation` | `invocation_id`, `conversation_id`, `tool_id`, `initiator_surface`, `initiator_actor`, `target_scope`, `status` | 是 | 中心端 / Edge |
| `ToolResult` | `invocation_id`, `status`, `summary`, `object_refs`, `evidence_refs`, `next_recommended_tools` | 否 | 中心端 / Edge |
| `AgentGoal` | `goal_id`, `conversation_id`, `status`, `autonomy_level`, `max_steps`, `steps_completed`, `workflow_id` | 是 | 中心端 |
| `AgentStep` | `step_id`, `goal_id`, `step_index`, `phase`, `decision`, `selected_tool_id`, `tool_invocation_id` | 是 | 中心端 |
| `SkillDefinition` | `skill_id`, `scope`, `mapped_tool_ids`, `internal_only` | 是 | 中心端 |
| `WorkerJob` | `job_id`, `skill_id`, `task_id`, `status`, `retry_count`, `queue_name` | 否 | 中心端 |

### 2.4 任务、上下文与结论对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `Task` | `task_id`, `project_id`, `version_id`, `us_id`, `status`, `current_resolution_id`, `max_healing_depth`, `healing_budget_used` | 是 | 中心端 |
| `TaskContext` | `task_context_id`, `task_id`, `status`, `related_feature_refs`, `evidence_refs` | 是 | 中心端 |
| `QualityProfile` | `quality_profile_id`, `task_context_id`, `status`, `risk_rating`, `verification_strategy` | 是 | 中心端 |
| `QualityAssetPack` | `asset_pack_id`, `us_id`, `version_id`, `status`, `scenario_set_ref`, `coverage_scope_ref`, `verification_plan_ref`, `case_set_ref`, `automation_asset_ref`, `performance_asset_ref`, `change_doc_ref`, `summary_ref`, `current_revision` | 是 | 中心端 |
| `AgentDecision` | `decision_id`, `task_id`, `source`, `decision_kind`, `status`, `confidence`, `evidence_refs` | 否 | 中心端 / Edge |
| `MergedResolution` | `resolution_id`, `task_id`, `resolution_kind`, `status`, `merged_from`, `approval_state` | 是 | 中心端 |
| `ApprovalRecord` | `approval_id`, `approval_kind`, `target_object_ref`, `status`, `approver_id`, `notes` | 是 | 中心端 |

### 2.5 执行、设备与同步对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `Run` | `run_id`, `task_id`, `execution_channel`, `status`, `environment_ref`, `evidence_refs`, `healing_depth`, `cooldown_until`, `last_failure_fingerprint` | 是 | 中心端 |
| `ExecutionEvidence` | `evidence_id`, `run_id`, `kind`, `storage_ref`, `hash`, `captured_at` | 是 | 中心端 / Edge |
| `FailureReport` | `failure_id`, `run_id`, `failure_kind`, `summary`, `evidence_refs`, `failure_fingerprint`, `healing_attempt_count` | 是 | 中心端 |
| `DeviceProfile` | `device_id`, `user_id`, `platform`, `client_version`, `trust_state`, `capability_summary` | 是 | 中心端 |
| `DeviceSession` | `device_session_id`, `device_id`, `user_id`, `status`, `heartbeat_at`, `policy_snapshot_id` | 是 | 中心端 / Edge |
| `CapabilityGrant` | `grant_id`, `user_id`, `device_id`, `project_id`, `task_id`, `capability_set`, `status` | 是 | 中心端 |
| `SyncEvent` | `sync_event_id`, `device_session_id`, `cursor`, `status`, `payload_ref`, `conflict_markers` | 是 | 中心端 / Edge |
| `LocalRunArtifact` | `artifact_id`, `device_session_id`, `run_id`, `path_hint`, `hash`, `upload_state` | 否 | Edge |

### 2.6 知识与审计对象

| 对象 | 关键字段 | 正式事实 | 写入方 |
| --- | --- | --- | --- |
| `ContextObject` | `object_id`, `type`, `status`, `confidence`, `source_refs`, `relationship_refs` | 是 | 中心端 |
| `RawAssetRecord` | `raw_asset_id`, `project_id`, `version_id`, `source_type`, `canonical_uri`, `content_ref`, `content_hash` | 是 | 中心端 |
| `ConnectorDefinition` | `connector_id`, `connector_type`, `status`, `config_ref` | 是 | 中心端 |
| `ConnectorBinding` | `binding_id`, `project_id`, `connector_id`, `status`, `scope_ref` | 是 | 中心端 |
| `ConnectorRun` | `run_id`, `binding_id`, `trigger_kind`, `status`, `checkpoint_ref` | 是 | 中心端 |
| `ConnectorCheckpoint` | `checkpoint_id`, `binding_id`, `cursor_ref`, `captured_at` | 是 | 中心端 |
| `MCPServerDefinition` | `server_id`, `name`, `transport_kind`, `status`, `endpoint_or_command_ref` | 是 | 中心端 |
| `MCPServerBinding` | `binding_id`, `project_id`, `server_id`, `status`, `policy_profile_id` | 是 | 中心端 |
| `MCPServerHealth` | `health_id`, `server_id`, `status`, `checked_at`, `details_ref` | 是 | 中心端 |
| `PolicySnapshot` | `policy_snapshot_id`, `scope`, `version`, `rules_ref` | 是 | 中心端 |
| `AuditEvent` | `event_id`, `event_type`, `occurred_at`, `actor_ref`, `conversation_id`, `tool_invocation_id`, `object_refs` | 是 | 中心端 / Edge |

## 3. 正式事实边界

- `UserIdentity / ProjectMembership / RoleBinding / AccessSession / ServicePrincipal / Project / Version / Session / ConversationSession / ConversationMessage / ConversationSummaryCheckpoint / ConversationLink / SessionKnowledgeBinding / USWorkItem / Baseline / AgentGoal / AgentStep / Task / TaskContext / QualityProfile / QualityAssetPack / Run / ExecutionEvidence / MergedResolution / ApprovalRecord / DeviceProfile / DeviceSession / CapabilityGrant / ContextObject / RawAssetRecord / ConnectorDefinition / ConnectorBinding / ConnectorRun / ConnectorCheckpoint / MCPServerDefinition / MCPServerBinding / MCPServerHealth / PolicySnapshot / AuditEvent` 属于正式事实对象。
- `ToolResult / WorkerJob / AgentDecision / CandidateKnowledge / LocalRunArtifact` 属于候选或执行中间对象。
- `AgentDecision` 不能直接推进正式放行、正式知识晋级或正式基线回写。
- `ToolInvocation` 是正式命令记录，但不是正式业务结论。

## 4. 核心状态机

### 4.1 Task

`draft -> analyzing -> pending_merge -> ready_for_review -> executing -> ready_for_release -> completed`

迁移规则：
- 只能由工具调用或系统 workflow 推动。
- `pending_merge` 只能由双端冲突或候选结论冲突触发。
- `completed` 仅在 `MergedResolution` 已批准且相关 `Run` 关闭后进入。
- `healing_budget_used` 超过 `max_healing_depth` 后，不得再次进入自动自愈链，必须转入人工处理。

### 4.2 ToolInvocation

`pending -> running -> waiting_confirmation / waiting_approval -> completed / failed / cancelled`

迁移规则：
- 高风险工具默认可进入 `waiting_confirmation` 或 `waiting_approval`。
- 只有 gate 通过后才能重新回到 `running`。
- `completed` 必须写出 `ToolResult` 和至少一个对象引用或结果摘要。

### 4.3 Run

`pending -> running -> succeeded / failed / retrying / pending_merge / closed`

迁移规则：
- `execution_channel` 只能是 `web_runner` 或 `desktop_local`。
- `pending_merge` 仅用于双端执行结论冲突或执行结果与候选结论冲突。
- `closed` 只在 failure/healing/release 链条结束后进入。
- 每次自动修复重试都必须递增 `healing_depth`。
- 当 `healing_depth >= Task.max_healing_depth` 时，禁止再次自动触发 `healing.propose`。
- 若 `cooldown_until` 未到，不得因相同 `last_failure_fingerprint` 立即再次进入自动重试。

### 4.4 AgentDecision

`provisional -> merged -> approved / rejected`

迁移规则：
- `provisional` 可由中心端或边缘端写入。
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

### 4.7 DeviceSession

`opening -> online -> degraded -> offline -> closed`

迁移规则：
- `degraded` 由心跳丢失、策略收紧或设备异常触发。
- `offline` 允许继续缓存 `SyncEvent` 和 `LocalRunArtifact`。
- `closed` 后只允许补传，不允许新本地高风险动作。

### 4.8 AccessSession

`active -> rotated -> revoked / expired`

迁移规则：
- `active` 由 OIDC/OAuth 登录完成后创建。
- `rotated` 由 refresh token rotation 触发。
- `revoked / expired` 后不得再签发新 access token。

### 4.9 ConversationSession

`draft -> active -> idle -> archived`

分支：

- `active -> merged`
- `active -> closed`

迁移规则：

- 首条消息写入后进入 `active`
- 被并入其他会话后进入 `merged`
- 归档后默认不出现在常规列表

### 4.10 ConversationMessage

`accepted -> streaming -> completed`

分支：

- `streaming -> interrupted`
- `streaming -> failed`
- `completed -> archived`

迁移规则：

- 流式 assistant 消息必须显式收到完成事件才可进入 `completed`
- 已完成消息正文 append-only

### 4.11 AgentGoal

`pending -> running -> paused -> completed`

分支：

- `running -> failed`
- `running -> cancelled`
- `paused -> running`
- `paused -> cancelled`

迁移规则：

- `paused` 必须带 `pause_reason`
- 同一 `ConversationSession` 同时只允许一个 `running` 的 `AgentGoal`

### 4.12 QualityAssetPack

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
- `AgentStep 0:1 ToolInvocation`
- `Task 1:1 TaskContext`
- `Task 1:1 QualityProfile`
- `Task 1:N Run`
- `Task 1:N AgentDecision`
- `Task 1:N MergedResolution`
- `Run 1:N ExecutionEvidence`
- `Project 1:N RawAssetRecord`
- `Project 1:N ConnectorBinding`
- `ConnectorDefinition 1:N ConnectorBinding`
- `ConnectorBinding 1:N ConnectorRun`
- `ConnectorBinding 1:N ConnectorCheckpoint`
- `Project 1:N MCPServerBinding`
- `MCPServerDefinition 1:N MCPServerBinding`
- `DeviceProfile 1:N DeviceSession`
- `DeviceSession 1:N SyncEvent`
- `Run 1:N LocalRunArtifact`

## 7. 实现约束

- 所有正式对象必须包含 `created_at / updated_at / created_by / updated_by / version` 审计字段。
- 所有正式对象必须支持外部稳定 ID，不暴露数据库自增主键。
- 软删只允许用于管理对象，不允许用于 `Run / Evidence / AuditEvent / ApprovalRecord`。
- `AuditEvent` 和 `ExecutionEvidence` 必须 append-only。
- 所有对象变更都必须能关联回 `tool_invocation_id`。
- `Baseline` 的 overlay 对象必须支持按 `object_id + field_path` 精确查询，以便合并查询和再基线化。

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
