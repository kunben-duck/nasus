# Nasus 后端运行时与工具协议

## 1. 目标

本文定义 `Conversation -> Agent Service -> ToolInvocation / AgentGoal / AgentSwarm -> Workflow / AgentGraph / Worker -> Domain Object` 的运行时协议，明确 Agent、Tool、Skill、Worker 和 Workflow 的职责边界。

## 2. 运行时分层

### 2.1 Conversation Orchestrator

职责：

- 接收主会话输入
- 读取当前空间、任务、版本、系统画像和最近执行状态
- 生成 `ClarificationRequest / DirectAnswer / ToolInvocationPlan / AgentGoalProposal`
- 为工具执行绑定上下文

输出：

- `conversation_summary`
- `tool_invocation_plan`
- `agent_goal_proposal`
- `recommended_tools`

执行前治理：

- Planner 可以从当前可见的完整 Tool Catalog 中选择工具，但输出必须由
  `AgentPlanPolicy` 校验工具注册、作用域、必需上下文、输入大小和重复动作。
- 只读查询链可以保留为 `ToolInvocationPlan`。
- 计划中包含任意写工具时必须提升为 `AgentGoalProposal`，不能作为不可中断的
  直接执行序列。
- 高风险工具允许进入计划，但确认和审批仍由 Tool Invocation Runtime 决定。

### 2.2 Agent Service Runtime

职责：

- 接收 `AgentGoalProposal`
- 创建和管理 `AgentGoal`
- 调用 `Agent Memory Manager` 组装上下文窗口
- 控制自主级别、预算、限流和中断恢复
- 为复杂目标创建 `AgentSwarmRun`
- 把候选结果交给 `Merge/Score`

硬约束：

- Agent Service 不能直接写正式领域对象。
- 每个 Agent 动作必须落到 `AgentStep`、`ToolInvocation`、`WorkerJob` 或 `AgentSwarmRun`。
- 所有 LLM 调用都必须经过 memory context packaging，不能由业务服务直接拼接上下文。

### 2.3 Agent Memory Runtime

职责：

- 维护 `working | conversation | project_long_term | candidate` 四类记忆
- 从 `ConversationSummaryCheckpoint`、`ContextObject`、`Baseline`、`Evidence` 和工具结果中抽取上下文
- 组装 THINK 阶段和 Skill LLM 调用所需的上下文窗口
- 将候选知识写入候选记忆，等待 merge / approval 晋级

硬约束：

- `project_long_term` 记忆只来自正式系统画像和已批准知识。
- `candidate` 记忆不能直接进入正式基线。
- 高风险工具的 policy/gate 约束永远不能被上下文裁剪。

### 2.4 Tool Invocation Runtime

每次工具执行都必须经过：

1. `context binding`
2. `policy check`
3. `capability check`
4. `confirmation / approval gate`
5. `workflow or direct execution dispatch`
6. `result materialization`
7. `audit append`

工具调用不是直接改业务状态，而是统一的命令执行层。

### 2.5 Durable Workflow Runtime

默认采用 `Temporal`，承接长生命周期流程：

- `ProjectInitializationWorkflow`
- `VersionCreationWorkflow`
- `TaskWorkflow`
- `RunWorkflow`
- `ApprovalWorkflow`
- `RebaselineWorkflow`
- `AgentGoalWorkflow`
- `AgentSwarmWorkflow`

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
- `waiting_confirmation`、`waiting_approval`、`waiting_run_completion` 这类长等待状态不得只保存在 `LangGraph` 内存或 graph checkpointer 中。
- `Temporal` 是生命周期真相源；`LangGraph` 只保存单次图执行所需的可恢复局部状态。
- 本地开发和单元测试可以使用 `NASUS_AGENT_WORKFLOW_RUNTIME=local`；生产环境必须使用 `temporal` 或等价耐久 workflow 实现。
- `TemporalClientWorkflowGateway` 是 API 侧默认生产 gateway。它启动 `NasusAgentGoalWorkflow`，要求 worker 暴露 `current_goal` query 并接收 `resume_goal` signal；查询回来的 `AgentGoal` 必须同步写回领域 read model。
- `NasusAgentGoalWorkflow` 由 `workflow-service` 承载，当前启动入口为 `python -m apps.api.app.agent_goal_workflow_worker`。
- Workflow activity 边界固定为 `start_agent_goal` 和 `resume_agent_goal`：activity 调用 `AgentLoopRuntime`，不能调用 `AgentService`，避免在 workflow 内再次创建 workflow。

### 2.6 Agent Graph Runtime

默认采用 `LangGraph`，但其职责已经从“单次工具执行窗口”扩展为双层编排：

#### 2.6.1 外层 Agent Loop Graph

承接高级目标的自主循环：

- `think`
- `act`
- `observe`
- `decide`

负责：

- 为 `AgentGoal` 选择下一步 Tool
- 根据 ToolResult 动态调整后续动作
- 产出 `GraphCompletion` 或 `GraphSuspension`

边界：

- `Agent Goal Plan Compiler` 负责把高层 `AgentGoalProposal` 编译为 `ToolPlanStep[]`。
- `Agent Graph Runtime` 负责执行编译后的 Think / Act / Observe / Decide 步骤，不应内联系统画像、质量闭环等领域计划补全逻辑。
- 若 `AgentGoalProposal` 只包含目标模板和 project 上下文，计划编译器必须能基于当前领域状态补齐工具链；例如系统画像构建可自动补齐或跳过 `system_image.sources.register / system_image.sources.ingest / system_image.context.materialize / system_image.baseline.initialize`。
- `llm_structured` 目标在每次存在待执行步骤的 OBSERVE 后调用通用
  `AgentReplanner`，输出只能是 `keep / replace_remaining / complete`。
- Replanner 的替换步骤必须再次经过 `AgentPlanPolicy`；provider 失败、输出非法
  或策略拒绝时保留原计划。质量闭环在 `release.assess` 成功前不能提前完成。
- 系统画像 follow-up 恢复链额外保留确定性的状态感知计划编译，以便模型不可用时
  仍能补齐 canonical 构建步骤。

#### 2.6.2 内层 Tool Graph

承接单个 Tool 内部的规划和路由：

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

统一约束：

- `LangGraph` 负责 Agent Loop 单次 iteration 或 Tool 单次执行窗口内的规划、路由和局部 checkpoint。
- 一旦遇到需要等待外部确认、审批或长时间执行结果回传的节点，graph 必须输出 `GraphSuspension`，由 `Temporal` 持久化并挂起 workflow。
- 恢复时由 `Temporal` 重新调用 graph，并传回 `graph_checkpoint_ref`、`resume_reason`、`resume_payload`。
- 本地开发和单元测试可以使用 `NASUS_AGENT_GRAPH_RUNTIME=local`；生产环境必须使用 `langgraph` 或等价图运行时。
- `LangGraphAgentLoopGateway` 是默认生产 graph gateway。它用 LangGraph `StateGraph` 承接外层 Agent Loop graph，节点内部仍只能调用 `ToolInvocationRuntime`，不得绕过 policy gate、approval gate、domain materialization 和 audit。
- 工具结果若返回 `requires_followup=true`，Agent Graph 必须暂停当前 `AgentGoal`，写入明确 `pause_reason`，等待用户或外部系统补齐输入后恢复；不得继续执行后续工具。
- `missing_source_binding` 是系统画像首版的标准 follow-up pause reason，用于阻止默认占位 source 直接进入正式画像构建链路。
- 恢复 follow-up pause 后，Agent Graph 不能只重放原始静态 step list。它必须让 `Agent Goal Plan Compiler` 基于最新领域状态重编译剩余工具链，将新增 `AgentStep` 插入同一个 `AgentGoal`，并保留原 `conversation -> agent goal -> tool invocation -> domain object` 审计链。
- 结构化 Planner 的候选计划最多包含 12 个工具动作；会话作用域 ID、
  幂等键、策略快照、确认状态和审批状态不能由模型控制。

### 2.7 Temporal / LangGraph 交接规则

固定流转如下：

1. `Conversation`、`AgentGoalProposal` 或显式 `ToolInvocation` 创建 workflow。
2. 若是高级目标，`Temporal` 启动 `AgentGoalWorkflow` 并调用外层 `LangGraph Agent Loop Graph`。
3. 若 `Agent Supervisor` 判断目标可并行，`Temporal` 启动 `AgentSwarmWorkflow`，创建多个 `AgentWorkerAssignment`。
4. 外层 graph 在单次 iteration 内完成：
   - THINK
   - 选择 Tool
   - 触发 Tool 执行或挂起
5. 当 Tool 真正执行时，`Temporal` 进入当前 tool 对应的 workflow 阶段，并调用内层 `LangGraph Tool Graph`。
6. 内层 graph 在单次执行窗口内完成：
   - 上下文装配
   - Tool 内部 Skill 路由
   - Worker 并行
   - 局部结果归并
7. 若 graph 得到可立即提交的结果，则直接返回 `GraphCompletion` 给 `Temporal`。
8. 若 graph 遇到以下节点，必须返回 `GraphSuspension`，而不是自行长期等待：
   - `waiting_confirmation`
   - `waiting_approval`
   - `waiting_run_completion`
9. `Temporal` 持久化 suspension，并把 workflow 状态切换到对应等待态。
10. 外部事件到达后，`Temporal` 恢复 workflow，再次调用对应 graph 完成后续步骤。

权责划分：

- `Temporal`
  - 生命周期状态机
  - 长等待
  - 重试/补偿/取消
  - 外部信号接收
- `LangGraph`
  - AgentGoal 单次 iteration planning
  - Tool 内 Skill/Worker 编排
  - 局部检查点
  - 输出 `GraphCompletion` 或 `GraphSuspension`

## 3. Tool / Skill / Worker 三层关系

### 3.1 Tool

- Tool 是产品级动作单元。
- Tool 是主 Agent、UI 和外部 API 共用的动作抽象。
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
- `initiator_surface=chat|ui|api|agent_loop`
- `initiator_actor=user|agent`
- `target_scope=central`
- `space_ref`
- `task_ref`
- `input_payload`
- `input_evidence_refs`
- `policy_snapshot_id`
- `idempotency_key`

服务端为幂等请求生成规范化 payload fingerprint，并以
`idempotency_scope + tool_id + idempotency_key` 建立数据库唯一约束。同一 key
与相同 payload 返回原 ToolInvocation；同一 key 与不同 payload 返回
`409 tool_idempotency_conflict`，不能静默复用或重复执行。

### 4.3 ToolInvocationResult

最小字段：

- `status`
- `summary`
- `object_refs`
- `evidence_refs`
- `requires_followup`
- `next_recommended_tools`
- `followup_gate_state`

### 4.3.1 执行占用与跨进程一致性

- PostgreSQL 是 ToolInvocation 状态的正式事实源；进程内 projection 仅用于兼容展示。
- 执行前必须原子占用：普通请求只允许 `pending -> running`，用户确认只允许
  `waiting_confirmation -> running`。
- 占用使用数据库行锁和状态前置条件；未取得占用的 API/Worker 必须读取并返回
  当前事实，不能再次调用 handler。
- API 重启、Temporal Worker 重启或多 API 副本不得改变确认、幂等和执行语义。

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

### 4.6 AgentSwarmRun

最小字段：

- `swarm_run_id`
- `parent_goal_id`
- `conversation_id`
- `swarm_kind=impact|scenario|case|failure|release|ingestion`
- `status=pending|running|merging|completed|partially_failed|failed|cancelled`
- `max_parallel_agents`
- `budget_ref`
- `merge_strategy`

### 4.7 AgentWorkerAssignment

最小字段：

- `assignment_id`
- `swarm_run_id`
- `worker_agent_kind=context|impact|scenario|case|execution|failure|release`
- `target_refs`
- `input_context_refs`
- `status=pending|running|completed|failed|cancelled`
- `agent_goal_id`
- `tool_invocation_refs`
- `candidate_result_ref`
- `timeout_seconds`
- `confidence`

### 4.8 WorkerResult

最小字段：

- `status=succeeded|failed|partial`
- `result`
- `confidence`
- `trace`
- `evidence_refs`
- `retryable`
- `error_code`

### 4.9 MergeInput / MergeOutput

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
- `waiting_state=confirmation|approval|run_completion`
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
- 高风险治理动作
- 审批等待
- 知识晋级
- 再基线化
- 证据上传恢复

### 可直接同步完成的动作

- 只读查询工具
- 轻量对象读取
- 无副作用的摘要生成
- Web Runner 状态查看

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
  - evidence 上传完成
  - workflow retry signal
- 恢复时，必须以 `Temporal workflow state` 为准，不允许前端直接恢复 graph。

## 8. 审计要求

以下节点必须写 `AuditEvent`：

- conversation message received
- tool invocation created
- gate entered
- gate approved / rejected
- agent goal created / proposed / started / paused / resumed / completed / failed / cancelled
- agent goal budget exhausted
- workflow started / resumed / failed
- worker started / completed / failed
- domain object materialized
- run completed
- evidence uploaded
- approval completed

约束：

- `AgentGoal` 生命周期审计必须由 `AgentGoalStateMachine` 产出的显式 `lifecycle_transition` 驱动，不能由通用 `status=running` patch 推断。
- `budget_exhausted` 是独立生命周期审计事件；进入该状态前不得继续发起新的业务工具调用。
- Agent 自驱链路中的工具审计和目标审计都可以携带 `agent_goal_id`，消费端需要通过 `entity_type` 或 `action` 区分目标生命周期事件与工具执行事件。
