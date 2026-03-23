# Nasus 后端运行时与工具协议

## 1. 目标

本文定义 `Conversation -> ToolInvocation -> Workflow / AgentGraph / Worker -> Domain Object` 的运行时协议，明确 Tool、Skill、Worker 和 Workflow 的职责边界。

## 2. 运行时分层

### 2.1 Conversation Orchestrator

职责：

- 接收主会话输入
- 读取当前空间、任务、版本、系统画像和最近执行状态
- 生成 `ToolInvocationPlan`
- 为工具执行绑定上下文

输出：

- `conversation_summary`
- `tool_invocation_plan`
- `recommended_tools`

### 2.2 Tool Invocation Runtime

每次工具执行都必须经过：

1. `context binding`
2. `policy check`
3. `capability check`
4. `confirmation / approval gate`
5. `workflow or direct execution dispatch`
6. `result materialization`
7. `audit append`

工具调用不是直接改业务状态，而是统一的命令执行层。

### 2.3 Durable Workflow Runtime

默认采用 `Temporal`，承接长生命周期流程：

- `ProjectInitializationWorkflow`
- `VersionCreationWorkflow`
- `TaskWorkflow`
- `RunWorkflow`
- `ApprovalWorkflow`
- `SyncWorkflow`
- `RebaselineWorkflow`

负责：

- checkpoint
- retry
- timeout
- cancel
- compensation
- wait for confirmation
- wait for approval
- resume

约束：

- 所有跨请求、跨分钟级等待、跨进程恢复的状态都属于 `Temporal`。
- `waiting_confirmation`、`waiting_approval`、`offline_replay_waiting` 这类长等待状态不得只保存在 `LangGraph` 内存或 graph checkpointer 中。
- `Temporal` 是生命周期真相源；`LangGraph` 只保存单次图执行所需的可恢复局部状态。

### 2.4 Agent Graph Runtime

默认采用 `LangGraph`，承接单次任务内的规划和路由：

- `build_task_context`
- `build_quality_profile`
- `impact.analyze`
- `verification.plan`
- `scenario.generate`
- `case.generate`
- `automation.generate`
- `failure.analyze`
- `healing.propose`
- `release.assess`

负责：

- 工具内部的 Skill 选择
- 局部并行
- human-in-the-loop 节点
- partial result 合并

约束：

- `LangGraph` 负责单次工具执行窗口内的规划、路由和局部 checkpoint。
- 一旦遇到需要等待外部确认、审批、设备恢复、长时间执行结果回传的节点，graph 必须输出 `GraphSuspension`，由 `Temporal` 持久化并挂起 workflow。
- 恢复时由 `Temporal` 重新调用 graph，并传回 `graph_checkpoint_ref`、`resume_reason`、`resume_payload`。

### 2.5 Temporal / LangGraph 交接规则

固定流转如下：

1. `Conversation` 或显式 `ToolInvocation` 创建 workflow。
2. `Temporal` 进入当前 tool 对应的 workflow 阶段，并调用 `LangGraph`。
3. `LangGraph` 在单次执行窗口内完成：
   - 上下文装配
   - Tool 内部 Skill 路由
   - Worker 并行
   - 局部结果归并
4. 若 graph 得到可立即提交的结果，则直接返回 `GraphCompletion` 给 `Temporal`。
5. 若 graph 遇到以下节点，必须返回 `GraphSuspension`，而不是自行长期等待：
   - `waiting_confirmation`
   - `waiting_approval`
   - `waiting_device_online`
   - `waiting_run_completion`
   - `waiting_sync_replay`
6. `Temporal` 持久化 suspension，并把 workflow 状态切换到对应等待态。
7. 外部事件到达后，`Temporal` 恢复 workflow，再次调用 `LangGraph` 完成后续步骤。

权责划分：

- `Temporal`
  - 生命周期状态机
  - 长等待
  - 重试/补偿/取消
  - 外部信号接收
- `LangGraph`
  - 单次任务窗口内的 planning
  - Tool 内 Skill/Worker 编排
  - 局部检查点
  - 输出 `GraphCompletion` 或 `GraphSuspension`

## 3. Tool / Skill / Worker 三层关系

### 3.1 Tool

- Tool 是产品级动作单元。
- Tool 是主 Agent、UI、Desktop 和外部 API 共用的动作抽象。
- Tool 必须显式声明风险、确认方式和输入输出 schema。

### 3.2 Skill

- Skill 是工具背后的内部能力组件。
- Skill 不直接暴露给最终用户作为主命令面，但可在高级界面中显示其来源。
- 一个 Tool 可以映射一个或多个 Skill。

### 3.3 Worker

- Worker 是 Skill 的执行单元。
- Worker 只处理明确输入，不承担全局规划。
- Worker 输出必须符合统一 envelope。

## 4. 核心协议

### 4.1 ToolDefinition

最小字段：

- `tool_id`
- `tool_kind`
- `scope`
- `risk_level`
- `confirmation_mode`
- `required_context`
- `input_schema_ref`
- `output_schema_ref`
- `produced_objects`
- `mapped_skill_ids`

### 4.2 ToolInvocationRequest

最小字段：

- `conversation_id`
- `tool_id`
- `initiator_surface=chat|ui|desktop|api`
- `initiator_actor=user|agent`
- `target_scope=central|edge`
- `space_ref`
- `task_ref`
- `input_payload`
- `input_evidence_refs`
- `policy_snapshot_id`

### 4.3 ToolInvocationResult

最小字段：

- `status`
- `summary`
- `object_refs`
- `evidence_refs`
- `requires_followup`
- `next_recommended_tools`
- `followup_gate_state`

### 4.4 SkillInvocationRequest

最小字段：

- `tool_invocation_id`
- `skill_id`
- `task_context_id`
- `quality_profile_id`
- `trigger_reason`
- `input_evidence_refs`
- `policy_snapshot_id`

### 4.5 WorkerJob

最小字段：

- `job_id`
- `tool_invocation_id`
- `skill_id`
- `worker_type`
- `payload`
- `retry_count`
- `timeout_sec`

### 4.6 WorkerResult

最小字段：

- `status=succeeded|failed|partial`
- `result`
- `confidence`
- `trace`
- `evidence_refs`
- `retryable`
- `error_code`

### 4.7 MergeInput / MergeOutput

`MergeInput`

- `task_id`
- `object_ref`
- `base_ref`
- `decision_refs`
- `run_refs`
- `evidence_refs`
- `policy_snapshot_id`

`MergeOutput`

- `resolution_kind`
- `status`
- `merged_from`
- `recommended_decision`
- `requires_approval`
- `auto_merged_patch`
- `conflict_entries`
- `frontend_payload_ref`

### 4.8 GraphSuspension / GraphCompletion

`GraphSuspension`

- `tool_invocation_id`
- `workflow_id`
- `graph_checkpoint_ref`
- `suspension_reason`
- `waiting_state=confirmation|approval|device_online|run_completion|sync_replay`
- `resume_token`
- `resume_context_ref`

`GraphCompletion`

- `tool_invocation_id`
- `graph_checkpoint_ref`
- `materialization_plan`
- `object_refs`
- `followup_actions`

### 4.9 结构化冲突合并协议

`Merge / Score` 对结构化对象默认采用 3-way merge：

- `base`：当前正式对象快照
- `left`：中心端候选结果
- `right`：边缘端或第二候选结果

处理规则：

- 标量字段冲突：若只有一侧修改，则自动采用修改侧；若双侧都修改且值不同，则生成手工冲突项。
- 对象字段冲突：递归按字段合并。
- 数组字段冲突：
  - 对具备稳定主键的数组，按主键做逐项 3-way merge
  - 对无稳定主键的数组，默认视为有序列表并产生冲突块，不做猜测性重排
- 富文本或长文本字段：使用 diff-match-patch 或等价文本 diff 产出 patch，但正式写入前仍需人工确认
- 任何自动合并结果都必须附带 `auto_merged_patch`
- 任何未自动解决的路径都必须进入 `conflict_entries`

## 5. Workflow 触发规则

### 必须进入 durable workflow 的动作

- 项目初始化
- 版本创建
- 长任务分析
- 自动化执行
- 高风险本地动作
- 审批等待
- 知识晋级
- 再基线化
- 离线补传恢复

### 可直接同步完成的动作

- 只读查询工具
- 轻量对象读取
- 无副作用的摘要生成
- 本地无风险状态查看

## 6. Gate 规则

- `confirmation_mode=none`
  - 直接执行
- `confirmation_mode=user_confirm`
  - 等待用户确认
- `confirmation_mode=approval_required`
  - 进入审批链
- `confirmation_mode=policy_only`
  - 只做策略校验，校验通过直接执行

高风险动作默认进入 `user_confirm` 或 `approval_required`。

## 7. 中断与恢复规则

- `ToolInvocationRuntime` 在收到 `GraphSuspension` 后，不直接把工具置为失败，而是：
  - 更新 `ToolInvocation.status`
  - 写入 `workflow_wait_state`
  - 记录 `graph_checkpoint_ref`
  - 发出对应 SSE 事件
- 恢复触发源包括：
  - 用户确认
  - 审批完成
  - Runner 回调
  - 设备重新在线
  - Sync replay 完成
- 恢复时，必须以 `Temporal workflow state` 为准，不允许前端或 Desktop 直接恢复 graph。

## 8. 审计要求

以下节点必须写 `AuditEvent`：

- conversation message received
- tool invocation created
- gate entered
- gate approved / rejected
- workflow started / resumed / failed
- worker started / completed / failed
- domain object materialized
- run completed
- sync applied
- approval completed
