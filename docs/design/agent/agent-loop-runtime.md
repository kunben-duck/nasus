# Nasus Agent Loop Runtime 设计

## 1. 文档定位

本文定义 Nasus 的 **Agent Loop Runtime**，即 Agent 自主循环执行引擎的核心设计。

Agent Loop Runtime 是 Nasus 实现 `agent-first` 架构承诺的关键组件。它使 Agent 能够像 Claude Code、Codex、OpenClaw 等自主 Agent 一样，在接收到用户的高级目标后，**自主规划、执行工具、观察结果、动态调整并持续推进**，直到目标完成或遇到需要人类介入的节点。

边界说明：

- `Agent Service` 是 Agent 主体模块的上层系统服务，负责目标、记忆、预算、Swarm 和结果收敛。
- `Agent Loop Runtime` 是 `Agent Service` 内部用于执行单个 `AgentGoal` 的循环引擎。
- 多 Agent 并行和记忆分层以 [Agent Service、记忆与蜂群模式设计](./agent-service-memory-and-swarm.md) 为准。

优先级关系：

- 产品行为与默认规则以 [最终特性说明书](../../final-feature-spec.md) 为准。
- 工具目录以 [./tool-catalog.md](./tool-catalog.md) 为准。
- 工具调用协议以 [../backend/runtime-and-tool-protocol.md](../backend/runtime-and-tool-protocol.md) 为准。
- 本文定义 Agent 在工具之上的自主循环执行协议、目标模型、安全边界和与现有组件的集成方式。
- 本文不替代 Agent Service 的记忆管理、Swarm 编排和跨目标调度设计。

## 2. 设计目标

- Agent 接收到用户的高级目标后，能够 **自主完成多步工具链** 而无需用户逐步指令。
- Agent 在每一步执行后 **观察结果并动态决策下一步**，而不是执行固定的预置计划。
- Agent 的思考过程和执行进度 **实时可见**，用户可随时跟踪和理解 Agent 行为。
- 用户可以 **随时打断** Agent 的自主循环，接管控制权或修改方向。
- 高风险动作仍然 **自动进入确认或审批闸口**，不因自主循环而绕过治理。
- Agent Loop 的生命周期 **必须持久化**，支持断连恢复、跨请求续接和长任务管理。
- 版本质量管理全链路 **必须可以作为一个目标整体自驱完成**。

## 3. 核心概念

### 3.1 Agent Goal（Agent 目标）

`AgentGoal` 是 Agent Loop 的顶层驱动对象，代表用户交给 Agent 的一个高级目标。

与 `ToolInvocationPlan` 的区别：

- `ToolInvocationPlan` 是 **有界初始计划** — 首发只用于低风险只读查询链；
  计划中一旦包含写工具，Orchestrator 必须先提升为 `AgentGoalProposal`。
- `AgentGoal` 是 **动态目标** — Agent 在每步执行后重新评估，决定下一步。

最小字段：

- `goal_id`
- `conversation_id`
- `session_id`
- `project_id`
- `version_id`
- `us_id` 可空
- `goal_template` 可空，匹配预定义模板时填充
- `goal_description` 用户原始意图的结构化描述
- `initiator_id`
- `status`
- `autonomy_level`
- `max_steps`
- `max_thinking_tokens`
- `steps_completed`
- `current_step_id` 可空
- `pause_reason` 可空
- `error_summary` 可空
- `workflow_id` 关联 Temporal workflow
- `created_at`
- `completed_at` 可空

### 3.2 Agent Step（Agent 步骤）

`AgentStep` 记录 Agent 循环中的每一次"思考-行动-观察"迭代。

最小字段：

- `step_id`
- `goal_id`
- `step_index`
- `phase` `thinking | acting | observing | deciding`
- `reasoning` Agent 的思考过程文本（可流式输出）
- `memory_context_hash` THINK 阶段所使用记忆包的稳定摘要，格式为 `sha256:*`
- `memory_context_summary` 记忆包的轻量摘要，例如包含的上下文 section、recent turns 和 checkpoint 数
- `memory_recent_turn_count`
- `memory_checkpoint_count`
- `available_tool_ids` 本次 THINK 可见工具目录 ID 列表
- `selected_tool_id` 可空
- `tool_invocation_id` 可空
- `observation_summary` 工具执行结果的结构化摘要
- `decision` `continue | pause | complete | fail | escalate`
- `decision_rationale` 为什么做出此决策
- `next_plan_hint` Agent 对下一步的初步规划
- `thinking_tokens_used`
- `started_at`
- `completed_at` 可空

### 3.3 Autonomy Level（自主级别）

Agent 的自主程度由 `autonomy_level` 控制：

| 级别 | 行为 | 适用场景 |
| --- | --- | --- |
| `full_auto` | Agent 自主完成所有低/中风险工具链，仅在高风险动作暂停 | 熟悉的质量闭环、日常进度查询 |
| `semi_auto` | Agent 自主执行，但在每个阶段转换时暂停等待用户确认 | 首次运行、需要用户复核的场景 |
| `step_by_step` | Agent 每执行一步都暂停等待用户确认 | 高敏感度、学习阶段 |

默认值：`semi_auto`

用户可在目标创建时指定，也可在运行中动态切换。

## 4. Agent Goal 状态机

`pending -> running -> paused -> running -> completed`

分支：

- `pending -> running`：目标创建后立即启动，或等用户确认后启动
- `running -> paused`：遇到 Gate 暂停、用户打断、阶段确认、预算耗尽
- `paused -> running`：用户确认、审批通过、预算追加
- `running -> completed`：目标达成
- `running -> failed`：不可恢复错误且重试耗尽
- `running -> cancelled`：用户主动取消
- `paused -> cancelled`：用户在暂停时取消

迁移规则：

- `running` 状态下 Agent Loop 持续执行，每个 iteration 产出一个 `AgentStep`。
- `paused` 的原因必须记录在 `pause_reason`，包括以下类别：
  - `gate_confirmation` — 工具需要用户确认
  - `gate_approval` — 工具需要审批
  - `phase_checkpoint` — 阶段转换等待（`semi_auto` 模式）
  - `user_interrupt` — 用户主动打断
  - `budget_exhausted` — steps 或 tokens 预算耗尽
  - `error_retry_exhausted` — 重试次数耗尽
  - `escalation` — Agent 判断需要人工介入
- `cancelled` 后对应 Temporal workflow 立即取消，已执行的工具结果保留不回滚。
- `completed` 时必须产出一个总结性 `AgentStep(decision=complete)`。

## 5. Agent Loop 执行协议

### 5.1 核心循环：Think → Act → Observe → Decide

```
Agent Loop 核心循环 (在 Temporal AgentGoalWorkflow 内)

loop:
  1. THINK
     - 读取当前目标、上下文、历史步骤
     - 通过 `Agent Memory Manager` 组装统一 `AgentMemoryContext`
     - 在 `AgentStep` 记录 `memory_context_hash / memory_context_summary / available_tool_ids`，但不得把完整 prompt 和 context dump 当作长期事实写入 step
     - 调用 LLM (planner model) 生成结构化候选计划；输出必须经过 `AgentPlanPolicy`
     - 对欠规格目标，调用 Agent Goal Plan Compiler 基于当前领域状态补齐可执行工具步骤
     - 产出 AgentStep(phase=thinking, reasoning=...)
     - 流式推送 SSE: agent.step.thinking

  2. ACT
     - 根据 THINK 结果选择 Tool
     - 更新 AgentStep(phase=acting, selected_tool_id=...)
     - 调用 Tool Invocation Runtime 执行 Tool
     - 若 Tool 需要 Gate → 产出 GraphSuspension → Temporal 挂起 → 暂停循环
     - 流式推送 SSE: agent.step.acting

  3. OBSERVE
     - 读取 ToolResult
     - Agent 生成观察摘要
     - 更新 AgentStep(phase=observing, observation_summary=...)
     - OBSERVE 完成后，`llm_structured` 目标由 Agent Replanner 根据最新领域状态
       在 `keep / replace_remaining / complete` 中重新决策
     - 系统画像 `requires_followup` 恢复链同时保留确定性的状态感知计划补齐，
       保证模型不可用时仍能恢复 canonical 构建链
     - 流式推送 SSE: agent.step.observing

  4. DECIDE
     - 根据 observation、goal、context、history 判断下一步
     - decision = continue | pause | complete | fail | escalate
     - 更新 AgentStep(phase=deciding, decision=..., next_plan_hint=...)
     - 流式推送 SSE: agent.step.decided

  5. CHECKPOINT
     - 将 AgentStep 持久化到 PostgreSQL
     - 更新 AgentGoal.steps_completed
     - 检查 budget 限制
     - 若 decision=continue → 回到 THINK
     - 若 decision=pause → Temporal 挂起
     - 若 decision=complete → 进入收尾
     - 若 decision=fail → 进入错误处理
     - 若 decision=escalate → 暂停并通知用户
end loop
```

### 5.2 THINK 阶段的 LLM 调用契约

THINK 阶段调用 `LLM Gateway`，使用专用 Prompt 模板 `agent_loop_planner`。

输入上下文（Context Packaging）：

- `goal_description` — 用户的原始目标
- `goal_template` — 匹配的预定义模板（若有）
- `step_history` — 最近 N 步的 reasoning + observation 摘要
- `current_task_context` — 当前 TaskContext 快照
- `available_tools` — 基于当前空间和权限过滤后的 Tool Catalog
- `current_space_context` — project_id / version_id / us_id 等
- `governance_constraints` — 哪些工具需要确认/审批
- `remaining_budget` — 剩余步骤数和 token 数

输出要求（Structured Output）：

- `reasoning` — 可审计的决策摘要，不保存或暴露模型私有思维链
- `next_tool_id` — 选择调用的工具
- `tool_input_payload` — 工具输入参数
- `confidence` — 对当前决策的置信度
- `should_pause_for_review` — 是否建议暂停等用户复核
- `estimated_remaining_steps` — 预估剩余步骤数

候选输出治理：

- `next_tool_id` 必须存在于当前用户和空间可见的 Tool Catalog
- 所有作用域 ID 由会话绑定，模型不能跨项目、版本、US 或 Task 改写
- 工具输入必须满足 `required_context`、目标 scope 和 JSON 大小限制
- 高风险工具可以被选择，但不能绕过 Tool Runtime 的确认与审批
- 多步计划最多 12 个工具动作；相同工具和相同输入不能重复
- 含写动作的计划必须进入 `AgentGoal`，获得暂停、恢复、审计和预算控制

### 5.3 ACT 阶段与 Tool Invocation Runtime 的集成

ACT 阶段复用现有 `Tool Invocation Runtime`，不绕过任何现有协议：

1. 创建 `ToolInvocation`，`initiator_actor=agent`，`initiator_surface=agent_loop`
2. 经过 `context binding → policy check → capability check → confirmation/approval gate`
3. 若工具需要进入 `waiting_confirmation` 或 `waiting_approval`：
   - Agent Loop 进入 `paused` 状态
   - Temporal workflow 挂起
   - SSE 推送 `agent.goal.paused`
   - 前端展示确认/审批卡片
   - 用户确认后 Temporal 恢复 → Agent Loop 从 OBSERVE 继续
4. 若工具可直接执行：
   - 进入 Temporal Activity / LangGraph 内部编排
   - 等待 `ToolResult` 返回

### 5.4 DECIDE 阶段的决策规则

Agent 的决策必须遵循以下硬约束：

- `continue` — 目标未完成，且有可执行的下一步
- `pause` — 需要用户输入、autonomy_level 要求暂停、或到达阶段检查点
- `complete` — 所有必要工具已执行完成，产出物满足目标要求
- `fail` — 遇到不可恢复错误，或重试次数耗尽
- `escalate` — Agent 判断当前情况超出自身能力，需要人工接管

`escalate` 的典型场景：

- 连续 3 次 THINK 无法确定下一步工具
- 工具执行结果与预期严重偏离
- 发现当前上下文缺少关键信息且无法通过工具补齐
- Agent 置信度低于阈值

## 6. 与现有组件的集成

### 6.1 Conversation Orchestrator 调整

`Conversation Orchestrator` 新增第四种输出类型：

- `ClarificationRequest` — 不变
- `ToolInvocationPlan` — 不变，用于简单的单步/多步确定性计划
- `DirectAnswer` — 不变
- **`AgentGoalProposal` — 新增**，当用户意图可映射为 Agent 自驱目标时产出

`AgentGoalProposal` 最小字段：

- `goal_template` 可空
- `goal_description`
- `suggested_autonomy_level`
- `estimated_steps`
- `estimated_duration`
- `target_refs`
- `requires_user_confirmation` 是否需要用户确认后再启动

决策规则：

- 若用户输入可映射到单个低风险只读工具 → 产出 `ToolInvocationPlan`
- 若用户输入可映射到只读的确定性步骤 → 产出 `ToolInvocationPlan`
- 若结构化计划包含任意写工具 → 提升为 `AgentGoalProposal`
- 若用户输入是一个高级目标，需要动态多步执行 → 产出 `AgentGoalProposal`
- 若用户输入明确包含"帮我完成"、"自动"、"全部"等自驱暗示词 → 优先产出 `AgentGoalProposal`
- 若用户在已有 `AgentGoal` 运行期间发消息 → 视为对当前目标的补充或打断

### 6.2 与 LangGraph 的关系

当前定义：

> `LangGraph` 负责单次工具执行窗口内的规划、路由和局部 checkpoint。

调整为：

> `LangGraph` 负责两个层级的编排：
> 1. **Agent Loop 层**：作为 Agent Goal 内的主循环引擎，执行 Think → Act → Observe → Decide 循环，每个 iteration 选择一个 Tool 并评估结果。
> 2. **Tool 内部层**：作为单个 Tool 内部的 Skill 路由、Worker 并行和局部结果合并引擎。

对应 LangGraph 图结构：

- **外层 Agent Loop Graph**
  - `prepare_node` 根据 start/resume 和 PostgreSQL 业务事实恢复游标。
  - `think_node` → `act_node` → `observe_node` → `decide_node`
  - `decide_node` 可输出 `GraphSuspension`（需要 Gate / 暂停）或 `GraphCompletion`（目标完成）
  - `thread_id={graph_name}:{goal_id}`，避免不同 graph 或目标共享 checkpoint 命名空间。
- **内层 Tool Graph**（不变）
  - 工具内部的 Skill 选择 → Worker 并行 → partial result 合并

持久化权责：

- `AgentGoal`、`AgentStep`、`ToolInvocation`、`AuditEvent` 是 PostgreSQL 中的 canonical business facts。
- LangGraph checkpointer 只保存图状态和节点游标；它不能替代领域 repository，也不能被 API 直接作为业务查询源。
- local/test 允许 `MemorySaver`；staging/prod 必须使用 `AsyncPostgresSaver` 和 `NASUS_LANGGRAPH_CHECKPOINT_BACKEND=postgres`。
- 每个 ACT 节点使用由 `goal_id + step_id + attempt` 推导的稳定幂等键，Temporal activity 重试和 graph resume 不得重复创建业务动作。

### 6.3 与 Temporal 的关系

新增 `AgentGoalWorkflow`：

- `AgentGoalWorkflow` 是 Agent Loop 的 durable workflow 容器。
- 负责：
  - Agent Loop 的持久化和恢复
  - Gate 暂停期间的 workflow 挂起
  - 用户打断后的优雅停机
  - 预算超限后的自动暂停
  - 长任务的 timeout 管理
  - 与 `TaskWorkflow`、`RunWorkflow`、`ApprovalWorkflow` 的协作
- 执行模型：
  - `AgentGoalWorkflow` 启动后，以 Temporal Activity 的形式调用 LangGraph Agent Loop Graph
  - 每个 Think → Act → Observe → Decide 循环是一个完整的 Activity
  - 若 Activity 返回 `GraphSuspension` → Temporal 挂起 workflow
  - 若 Activity 返回 `continue` → Temporal 调度下一个 Activity
  - 若 Activity 返回 `complete` → Temporal 完成 workflow

### 6.4 与 Tool Invocation Runtime 的关系

不变。Agent Loop 的 ACT 阶段完全复用现有 `Tool Invocation Runtime`：

- `initiator_surface=agent_loop`
- `initiator_actor=agent`
- 所有 policy check、gate、审计一律不跳过
- `tool_invocation_id` 关联回 `AgentStep.tool_invocation_id`

### 6.5 与 Agent Memory / Swarm 的关系

- 每次 THINK 前，Agent Loop 必须向 `Agent Memory Manager` 请求上下文窗口，而不是自行读取全部消息或拼接长期记忆。
- `AgentStep` 完成后，关键 observation 和用户反馈必须提交给 `Agent Memory Manager`，由它决定是否形成工作记忆、会话记忆或候选记忆。
- 当 Agent Loop 判断目标需要并行执行时，不能直接在 loop 内自行创建无管理的子任务；必须向 `Agent Supervisor` 请求创建 `AgentSwarmRun`。
- `AgentSwarmRun` 完成后，其合并摘要作为 observation 输入下一次 DECIDE 阶段。

### 6.6 V1 实现状态与强制收敛项

当前首版实现已经具备：

- live 模型基于当前 `AgentMemoryContext + Tool Catalog` 生成四类结构化决策
- 任意目录工具都可进入候选计划，而不是只识别少量关键词
- 写计划自动提升为可中断、可恢复、可审计的 `AgentGoal`
- `AgentPlanPolicy` 执行工具白名单、作用域绑定、上下文、目标 scope、
  计划长度、输入大小、重复动作和质量闭环完成条件校验
- THINK / ACT / OBSERVE / DECIDE 事实写入 PostgreSQL，ACT 统一经过
  `ToolInvocationRuntime`
- 系统画像构建在补充 source 后可以在原 `AgentGoal` 内增量补齐剩余步骤
- `llm_structured` 目标在每次存在待执行步骤的 OBSERVE 后调用通用
  Agent Replanner，可保留或替换剩余计划，也可在完成契约满足后提前收尾
- 每次重规划形成 `agent.goal.replanned` 审计事实；provider 失败、输出非法或
  策略拒绝时保留原有已校验计划
- 质量闭环在 `release.assess` 成功前不能由 Replanner 提前标记完成
- staging/prod 的自由文本初始规划在 provider 失败或结构化输出非法时仅允许
  回退到只读决策；若确定性候选包含写工具，必须返回
  `planner_provider_unavailable` 澄清消息，并保证不创建 `AgentGoal`、
  `ToolInvocation` 或领域事实
- UI canonical action 必须携带受支持的 `canonical_action_id`，且消息内容与固定
  Tool Contract 匹配后才可走确定性入口；不得仅凭文案猜测来源，并仍完整继承
  RBAC、confirmation、approval 和 policy gate

正式 V1 已实现并持久化 `max_steps / max_model_calls / max_thinking_tokens /
max_runtime_seconds / max_no_progress_observations`，预算耗尽或
重复无进展 observation 会在创建下一条业务 `ToolInvocation` 前暂停目标。仍必须完成、
且当前不得被描述为已完成：

- 货币成本预算与跨实例 per-provider rate budget
- 连续低置信规划和跨不同工具组合的循环链路熔断
- 通用 Agent Swarm 的拆分、结果合并和冲突治理；当前并行仅覆盖受控场景
- candidate memory 的晋级、冲突合并和审批闭环

## 7. 版本质量管理 Goal Templates

### 7.1 `us.quality.complete` — US 质量闭环

```
目标：完成指定 US 的完整质量闭环

输入：
  - us_id
  - version_id
  - base_url（进入 run.start 前必需，可在 Goal 运行中由用户补充）

自驱链路：
  1. us.task.start                     # 启动 US 质量任务
  2. quality.scope.generate           # 生成测试范围
  3. quality.scenario.generate        # 生成测试场景
  4. quality.plan.generate            # 生成验证计划
  5. quality.case.generate            # 生成测试用例
  6. automation.generate              # 生成并版本化可审阅自动化资产，不执行
  7. run.start                        # 选择已保存资产 revision 和显式 base_url 后触发执行
  8. [观察执行结果]
     ├── 全部通过 → 进入 Step 11
     └── 存在失败 → 进入 Step 9
  9. failure.analyze                  # 分析失败
  10. healing.propose                 # 生成修复
      → run.start (re-run)           # 重新执行
      → 回到 Step 8 (max_healing_depth 控制)
  11. quality.asset-pack.refresh      # 汇总资产
  12. quality.change-doc.generate     # 生成变更文档

暂停点：
  - Step 7 前若缺少 base_url，暂停并请求目标环境
  - Step 7 前暂停（semi_auto 模式下，确认资产 revision、目标环境和执行计划）
  - healing 超过 max_healing_depth 后暂停
  - approval.request 自动进入 Gate

预估步骤：12-20（取决于失败和重试次数）
```

### 7.2 `version.quality.assess` — 版本质量评估

```
目标：评估指定版本的整体质量状态和放行准备度

输入：
  - version_id

自驱链路：
  1. version.progress.get             # 查询版本进度
  2. [遍历未完成 US]
     └── 对每个 US: us.status.get     # 查看 US 状态
  3. risk.summary.get                 # 生成版本风险摘要
  4. release.advice.get               # 获取放行建议
  5. 输出版本质量评估报告

暂停点：
  - 发现高风险未闭环项时暂停并提示用户

预估步骤：5-15（取决于 US 数量）
```

### 7.3 `project.onboard` — 项目初始化接入

```
目标：完成项目的初始化接入和系统画像生成

输入：
  - project_name
  - code_source_ref
  - historical_us_source_ref
  - historical_test_asset_source_ref

自驱链路：
  1. project.create                   # 创建项目空间
  2. project.assets.connect           # 创建 source slots 和项目资产引用
  3. system_image.sources.register    # 注册必需代码 source 和已提供的可选 source
  4. system_image.sources.ingest      # 摄入真实 source
  5. system_image.context.materialize # 物化 ContextObject / 关系 / 指标
  6. system_image.baseline.initialize # 初始化 Official Baseline
  7. project.status.get               # 检查接入状态

暂停点：
  - 缺少代码 source 时，进入 pause(reason=missing_source_binding)
  - 缺少历史 US 或历史测试资产时，记录 coverage gap 并提示补充，但允许继续生成低置信代码基线
  - source ingestion 部分失败时，进入 pause(reason=requires_followup)
  - context materialize 输出低置信或冲突对象时，进入 pause(reason=requires_followup)
  - system_image.baseline.initialize 是高风险动作，自动进入 Gate
  - 系统画像生成后暂停，等用户审核

预估步骤：7-12
```

硬规则：

- `system_image.baseline.initialize` 不得在代码 source 缺失、必需 source ingestion 失败或 context 未物化时执行；可选 source 缺失不得单独阻断。
- 用户补齐 source 或确认 gate 后，必须恢复同一个 `AgentGoal`，不得新建平行目标。
- `project.assets.connect` 只能创建 source slots 或资产引用，不能替代 `system_image.sources.register / ingest / materialize`。

### 7.4 `failure.fix.and.rerun` — 失败修复与重跑

```
目标：分析执行失败，生成修复方案，重新执行并验证

输入：
  - run_id 或 task_id

自驱链路：
  1. failure.analyze                  # 分析失败原因
  2. healing.propose                  # 生成修复建议
  3. [等待用户确认 patch]
  4. run.start                        # 重新执行
  5. [观察执行结果]
     ├── 通过 → complete
     └── 失败 → 回到 Step 1 (max_healing_depth 控制)

暂停点：
  - 修复 patch 确认（semi_auto 模式下）
  - healing_depth 超限后强制暂停

预估步骤：3-10
```

## 8. SSE 事件扩展

### 8.1 新增事件类型

在 [../backend/api-and-events.md](../backend/api-and-events.md) 的公开事件类型基础上，新增以下 Agent Loop 事件：

- `agent.goal.created` — 目标创建
- `agent.goal.started` — 目标开始执行
- `agent.goal.paused` — 目标暂停（含原因）
- `agent.goal.resumed` — 目标恢复执行
- `agent.goal.completed` — 目标完成
- `agent.goal.failed` — 目标失败
- `agent.goal.cancelled` — 目标取消
- `agent.step.thinking` — Agent 正在思考（可流式）
- `agent.step.thinking.delta` — 思考过程的增量文本
- `agent.step.acting` — Agent 正在执行工具
- `agent.step.observing` — Agent 正在观察结果
- `agent.step.decided` — Agent 做出决策

### 8.2 事件信封扩展

Agent Loop 事件在统一 SSE 信封基础上增加：

- `goal_id`
- `step_id`
- `step_index`
- `phase`
- `decision`
- `progress_percent` 可选
- `estimated_remaining_steps` 可选

### 8.3 Thinking 流式输出

`agent.step.thinking.delta` 事件遵循与 `assistant.message.delta` 相同的流式协议：

- `stream_id`
- `step_id`
- `sequence`
- `chunk_index`
- `is_final`
- `content_type=thinking`

约束：

- 同一 `step_id` 下的 thinking delta 必须严格递增 `sequence`
- 前端必须能实时展示思考过程文本（可折叠/展开）

## 9. API 扩展

### 9.1 新增接口

| 接口 | 用途 |
| --- | --- |
| `POST /v1/agent-goals` | 创建 Agent 目标，启动 Agent Loop |
| `GET /v1/agent-goals/{id}` | 获取目标状态和步骤历史 |
| `GET /v1/agent-goals/{id}/events` | 目标事件流 |
| `POST /v1/agent-goals/{id}/interrupt` | 打断正在运行的 Agent Loop |
| `POST /v1/agent-goals/{id}/resume` | 恢复暂停的 Agent Loop |
| `POST /v1/agent-goals/{id}/cancel` | 取消 Agent 目标 |
| `PATCH /v1/agent-goals/{id}/autonomy` | 动态调整自主级别 |
| `POST /v1/agent-goals/{id}/feedback` | 向运行中的 Agent 提供方向性反馈 |

### 9.2 接口语义

`POST /v1/agent-goals`

- 请求体：
  - `conversation_id`
  - `goal_template` 可空
  - `goal_description`
  - `target_refs`
  - `autonomy_level`
  - `max_steps` 默认 50
  - `max_thinking_tokens` 默认 500000
- 同步返回：`goal_id`、初始 `status`
- 异步行为：通过 `agent-goals/{id}/events` 推送所有步骤事件

`POST /v1/agent-goals/{id}/interrupt`

- 效果：Agent 在当前步骤完成后暂停，不中断正在执行的 Tool
- 若当前正在执行 Tool → 等 ToolResult 返回后暂停
- 若当前正在 THINK → 等 LLM 调用完成后暂停
- `pause_reason=user_interrupt`

`POST /v1/agent-goals/{id}/feedback`

- 请求体：
  - `message` 用户反馈文本
  - `directive` 可选的结构化指令（如 `skip_current_step`、`change_strategy`、`add_focus`）
- 效果：反馈会被注入下一次 THINK 阶段的上下文中
- Agent 不一定采纳，但必须在 reasoning 中说明

## 10. 安全与预算控制

### 10.1 步骤预算

- 每个 `AgentGoal` 有 `max_steps` 限制，默认 50。
- 每步完成后检查 `steps_completed >= max_steps`。
- 超限后自动暂停，`pause_reason=budget_exhausted`。
- 用户可通过 `PATCH /v1/agent-goals/{id}` 追加预算后 resume。

### 10.2 Token 预算

- 每个 `AgentGoal` 有 `max_thinking_tokens` 限制。
- THINK 阶段的 LLM 调用 token 计入 `step.thinking_tokens_used`。
- Tool 内部的 LLM 调用走 Tool 自身的 token 预算，不计入 Goal 预算。
- 超限后自动暂停，`pause_reason=budget_exhausted`。

### 10.3 循环检测

- Agent Loop 必须检测"重复行为"：
  - 连续 3 次选择同一 Tool 且输入相同 → 触发 `escalate`
  - 连续 2 次 THINK 输出相同的 next_plan_hint → 触发 `escalate`
  - Healing 循环超过 `Task.max_healing_depth` → 强制 `pause`
  - 同一 `failure_fingerprint` 在冷却窗口内重复出现 → 强制 `pause`

### 10.4 工具调用速率限制

- Agent Loop 在单位时间内的工具调用次数不得超过配置上限。
- 默认：每分钟最多 10 次工具调用。
- 超限后自动进入短暂 cooldown，不直接失败。

### 10.5 Gate 规则继承

Agent Loop 完全继承 [../backend/execution-governance.md](../backend/execution-governance.md) 中定义的 Gate 规则：

- `risk_level=low` → Agent 自主执行
- `risk_level=medium` → `full_auto` 模式自主执行，`semi_auto` 模式暂停
- `risk_level=high` → 始终暂停等用户确认
- `risk_level=critical` → 始终进入审批链

### 10.6 权限边界

- Agent Loop 不拥有超出当前用户的权限。
- Agent 的 `effective_actor` 始终是启动 Goal 的用户。
- 即使在 `full_auto` 模式下，RBAC 与 PolicySnapshot 仍全部生效。

## 11. 用户打断与 Agent 协作

### 11.1 用户消息处理

当 Agent Loop 正在运行时，用户在同一 conversation 中发送消息：

- 若消息是方向性反馈（如"跳过性能测试"、"重点关注支付模块"）：
  - 通过 `/agent-goals/{id}/feedback` 注入
  - Agent 在下一次 THINK 时消费
  - 不中断当前执行
- 若消息是明确的打断指令（如"停下来"、"等一下"、"我要改方向"）：
  - 触发 `/agent-goals/{id}/interrupt`
  - Agent 在当前步骤完成后暂停
  - 暂停后用户可修改目标或手动执行其他操作
- 若消息是新的独立问题（如"帮我查一下 XXX"）：
  - 走正常的 Conversation Orchestrator 处理
  - Agent Loop 继续运行，两者并行不冲突
  - 但同一 conversation 不允许同时运行两个 AgentGoal

### 11.2 Agent Loop 恢复

用户打断或 Gate 暂停后的恢复方式：

- `POST /v1/agent-goals/{id}/resume`
  - 可选附带 `resume_message`，作为下一次 THINK 的额外上下文
  - 可选修改 `autonomy_level`
  - 可选修改 `max_steps`
- 前端显示 "Agent 已暂停" 卡片，带有以下按钮：
  - "继续" → resume
  - "修改方向" → resume with feedback
  - "取消任务" → cancel
  - "切换为手动" → 将 autonomy_level 改为 step_by_step

## 12. 前端消费指导

### 12.1 ChatTimeline 扩展

Agent Loop 在 ChatTimeline 中的展示方式：

- **Goal 启动卡片**：显示目标描述、预估步骤数和自主级别
- **Thinking 展开区**：可折叠/展开的思考过程文本，实时流式更新
- **Step 进度条**：显示 "Step 3/12: 正在生成测试场景..."
- **Tool 执行卡片**：展示当前正在执行的工具和中间结果
- **Gate 确认卡片**：Agent 暂停在 Gate 时，显示确认/审批按钮
- **Decision 标签**：每步结束后显示 Agent 的决策（continue / pause / complete）
- **Goal 完成卡片**：显示最终结论、产出物列表和执行统计

### 12.2 查询键扩展

在现有查询键基础上新增：

- `["agent-goal", goalId]`
- `["agent-goal-steps", goalId]`

### 12.3 EventReducer 扩展

前端 EventReducer 需要处理 `agent.*` 事件系列：

- `agent.step.thinking.delta` → 增量更新 thinking 文本区
- `agent.step.acting` → 更新步骤状态为 "执行中"
- `agent.step.decided` → 更新步骤状态为 "已完成"
- `agent.goal.paused` → 显示暂停卡片和操作按钮
- `agent.goal.completed` → 显示完成卡片

## 13. 审计要求

以下节点必须写 `AuditEvent`：

- Agent Goal 创建
- Agent Goal 状态变更（started / paused / resumed / completed / failed / cancelled）
- Agent Goal 预算耗尽（`budget_exhausted`），必须在继续创建业务 `ToolInvocation` 前暂停
- Agent Step 的每次 DECIDE（记录 decision 和 rationale）
- Agent 选择的每个 Tool（关联 tool_invocation_id）
- 用户打断操作
- 用户 feedback 注入
- 预算超限事件
- 循环检测触发事件
- autonomy_level 动态变更

实现约束：

- 生命周期审计必须由 `AgentGoalStateMachine` 显式输出的 `lifecycle_transition` 触发，普通 `AgentStep` patch、SSE 增量或 read-model 同步不得被推断为生命周期事件。
- `GET /v1/audit-events?agent_goal_id=...` 会同时返回目标生命周期审计和该目标触发的工具审计；前端与治理视图必须按 `entity_type` 或 `action` 分组展示。

## 14. 实现约束

- `AgentGoal` 和 `AgentStep` 必须持久化到 PostgreSQL，不能只保存在 LangGraph 内存中。
- Agent Loop 的 Temporal workflow 必须可重入，断连或服务重启后能从最后一个 `AgentStep` 恢复。
- 正式 worker 入口固定为 `python -m apps.api.app.infrastructure.workflow.agent_goal_workflow_worker`；根目录同名模块只作为迁移期兼容转发层。
- THINK 阶段的 LLM 调用必须通过 `LLM Gateway`，不能直接调用 Provider。
- Agent 的 reasoning 文本默认保存到数据库，但可按策略控制敏感内容的存储粒度。
- Agent Loop 的 Tool 调用与普通 UI/chat 触发的 Tool 调用共享同一个 `Tool Invocation Runtime`，不能建立绕过审计和治理的"快速通道"。
- 同一 conversation 同一时间只允许一个活跃的 `AgentGoal(status=running)`。
- Goal Templates 以配置形式存储在数据库中，不硬编码在代码里，支持运辝时添加和修改。
- `AgentStep.reasoning` 必须支持流式输出，前端不能等整个 THINK 完成后才展示。

## 15. 与现有文档的关系

| 文档 | 关系 |
| --- | --- |
| `design/backend/system-design.md` | Agent Loop Runtime 是后端新增的一个逻辑层，位于 `Conversation Layer` 和 `Tool Contract Layer` 之间 |
| `design/agent/conversation-runtime.md` | Orchestrator 在会话运行时中定义 `AgentGoalProposal` 输出类型 |
| `design/backend/runtime-and-tool-protocol.md` | LangGraph 的角色从"工具内部编排"扩展为"Agent Loop + 工具内部"双层编排 |
| `design/backend/domain-model.md` | 新增 `AgentGoal` 和 `AgentStep` 两个领域对象 |
| `design/backend/api-and-events.md` | 新增 Agent Loop 相关 API 和 SSE 事件 |
| `design/backend/execution-governance.md` | Gate 规则完全继承，不做任何绕过 |
| `design/agent/tool-catalog.md` | Tool Catalog 不变，Agent Loop 是 Tool 的消费者而不是替代者 |
| `design/agent/llm-runtime.md` | 新增 `agent_loop_planner` Prompt 模板和对应的 token 预算维度 |
| `design/platform/auth-and-access-design.md` | Agent 权限边界不变，`effective_actor` 始终是用户 |
