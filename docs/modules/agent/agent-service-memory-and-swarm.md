# Agent Service、记忆与蜂群模式设计

## 1. 文档定位

本文定义 Nasus Agent 主体模块的上层架构：`Agent Service`。  
`Agent Service` 是整个系统的主驱动服务，不是页面聊天框，也不是单个 `AgentGoalWorkflow`。

它负责：

- 管理用户目标和会话上下文
- 维护短期记忆、长期记忆和工作记忆
- 选择工具并发起 `ToolInvocation`
- 在复杂任务中拆分并行子任务，调度多个 Agent Worker 协作
- 合并候选结果，并通过治理链路推进正式对象

`Agent Loop Runtime` 只负责单个 `AgentGoal` 的 Think -> Act -> Observe -> Decide 循环；`Agent Service` 负责多个目标、多个会话、多个 worker agent 和记忆系统之间的全局协调。

## 2. 设计原则

- Nasus 整体是一个 agent-first 的质量闭环平台，所有核心功能都必须能被 Agent 通过工具调用。
- Agent 是主驱动层，但不能绕过工具、策略、审批和正式事实边界。
- 记忆必须结构化、可审计、可过期、可晋级，不能只是 prompt 历史。
- 并行 Agent 蜂群只能产出候选结果，正式结论必须经过 `Merge/Score` 和 `Approval Control`。
- 多 Agent 并行是效率手段，不是治理豁免；每个子任务仍必须关联 `AgentGoal / AgentStep / ToolInvocation / WorkerJob / AuditEvent`。

## 3. Agent Service 架构

核心组件：

| 组件 | 职责 |
| --- | --- |
| `Agent Supervisor` | 接收 `AgentGoalProposal`，决定目标模板、自主级别、预算和是否拆分为并行子任务 |
| `Agent Memory Manager` | 维护工作记忆、会话记忆、项目长期记忆和候选记忆的读取、写入、摘要和晋级 |
| `Agent Goal Runtime` | 承载单个目标的耐久循环，即 `AgentGoalWorkflow + Agent Loop Graph` |
| `Agent Swarm Coordinator` | 对复杂任务拆分多个 `AgentWorkerAssignment`，并发调度专门 worker agent |
| `Agent Result Merger` | 汇总多个 worker agent 的候选输出，生成 `AgentDecision` 或 `MergedResolution` 输入 |
| `Policy / Budget Guard` | 控制工具权限、确认/审批、token、步骤数、并发数和自愈深度 |

标准链路：

```text
Conversation
  -> Conversation Orchestrator
  -> AgentGoalProposal
  -> Agent Supervisor
  -> Memory Context Assembly
  -> AgentGoalWorkflow
  -> ToolInvocation / Agent Swarm
  -> AgentDecision
  -> Merge/Score
  -> Domain Object / Approval
```

## 4. 记忆分层

### 4.1 Working Memory

单次 `AgentGoal` 内有效的临时状态。

内容包括：

- 当前目标
- 当前 step history
- 当前工具结果摘要
- 当前可见对象引用
- 当前预算和约束

存储要求：

- 持久化在 `AgentGoal / AgentStep` 和 workflow checkpoint 中
- 用于恢复运行，不直接晋级为项目知识
- 目标结束后可摘要为会话记忆

### 4.2 Conversation Memory

用户与 Agent 在某个空间内的多轮交互记忆。

内容包括：

- 最近消息
- `ConversationSummaryCheckpoint`
- 用户反馈
- 已确认的上下文偏好
- 会话级工具调用和结果摘要

存储要求：

- 以 `ConversationSession / ConversationMessage / ConversationSummaryCheckpoint` 为事实源
- 支持搜索、归档、合并和恢复
- 默认属于 session-only，不直接污染项目基线

### 4.3 Project Long-term Memory

项目级长期质量记忆，即系统画像和正式基线。

内容包括：

- `ContextObject`
- `Baseline`
- 历史质量资产
- 历史执行证据
- 已批准的风险模式、失败归因和质量规则

存储要求：

- 通过 `Unified Context Engine` 与 `Baseline Service` 读取
- 只有通过审批的候选知识才能晋级
- 是 Agent 进行质量判断的长期上下文来源

### 4.4 Candidate Memory

Agent 在任务中发现但尚未正式确认的候选知识。

内容包括：

- 候选风险模式
- 候选系统关系
- 候选验证策略
- 候选失败归因
- 候选放行判断

存储要求：

- 存为 `AgentDecision`、`CandidateKnowledge` 或 `MergedResolution` 输入
- 必须带 evidence refs、source refs、confidence 和来源 Agent
- 只有经 `Merge/Score + Approval Control` 后才能进入长期记忆

## 5. Context Window 组装规则

LLM 调用前必须由 `Agent Memory Manager` 组装上下文窗口，不能由业务代码随意拼接 prompt。

默认顺序：

1. 系统级安全与治理约束
2. 当前空间上下文
3. 当前目标和任务状态
4. 最新用户消息和最近对话
5. 会话摘要 checkpoint
6. 相关系统画像和长期记忆
7. 当前工具目录和可执行权限
8. 预算、并发、风险和确认要求

裁剪规则：

- 近期消息优先保留原文
- 历史消息优先保留摘要
- 长期记忆只注入与当前目标相关的对象引用和摘要
- 高风险工具的 policy/gate 约束永远不可裁剪
- 被用户显式引用的证据和对象必须进入窗口

## 6. Agent Swarm 模式

### 6.1 适用场景

以下任务允许进入 Agent Swarm：

- 大版本多 US 并行质量评估
- 多模块影响分析
- 多角色或多路径测试场景生成
- 多执行失败的批量归因
- 大型系统画像接入后的关系抽取和交叉验证

以下任务不允许直接 Swarm 自动完成：

- 基线正式回写
- 放行最终审批
- 权限或策略变更
- 高风险执行动作

这些动作可以被 swarm 产出建议，但必须进入确认或审批 gate。

### 6.2 Swarm 对象

`AgentSwarmRun` 表示一次多 Agent 并行任务。

最小字段：

- `swarm_run_id`
- `parent_goal_id`
- `conversation_id`
- `swarm_kind=impact|scenario|case|failure|release|ingestion`
- `status=pending|running|merging|completed|failed|cancelled`
- `max_parallel_agents`
- `budget_ref`
- `merge_strategy`
- `created_at`
- `completed_at`

`AgentWorkerAssignment` 表示一个子 Agent 任务。

最小字段：

- `assignment_id`
- `swarm_run_id`
- `worker_agent_kind=context|impact|scenario|case|execution|failure|release`
- `target_refs`
- `input_context_refs`
- `status=pending|running|completed|failed|cancelled`
- `agent_goal_id` 可空
- `tool_invocation_refs`
- `candidate_result_ref`
- `confidence`

### 6.3 Swarm 执行协议

```text
Agent Supervisor
  -> 创建 AgentSwarmRun
  -> 拆分 AgentWorkerAssignment
  -> 并发执行 worker agent
  -> 每个 worker 只通过 ToolInvocation 执行动作
  -> Agent Result Merger 汇总候选结果
  -> Merge/Score 输出冲突、置信度和推荐结论
  -> 必要时进入 Approval Control
```

硬约束：

- 同一 `ConversationSession` 默认只允许一个主 `AgentGoal` 运行，但该 `AgentGoal` 内可以启动一个或多个 `AgentSwarmRun`。
- Swarm 并发数必须受 `max_parallel_agents` 和租户/项目预算控制。
- 每个子 Agent 必须有明确目标、输入、输出 schema 和超时。
- 子 Agent 不得直接写正式事实对象。
- Swarm 合并阶段必须保留冲突字段、来源、证据和置信度。

## 7. 预算、限流与防死循环

Agent Service 必须统一控制：

- `max_steps`
- `max_thinking_tokens`
- `max_parallel_agents`
- `max_tool_invocations_per_goal`
- `max_healing_depth`
- `rate_limit_per_project`
- `rate_limit_per_user`

触发阈值后：

- 普通目标进入 `paused`
- 高风险目标进入 `escalate`
- 自动自愈链进入 `fallback_to_human`
- Swarm 停止创建新 assignment，但保留已完成候选结果用于人工审阅

## 8. 前端呈现要求

Web Portal 需要把 Agent Service 的存在可视化，而不是只显示聊天气泡。

最低要求：

- `AgentGoalCard` 展示目标、状态、自主级别、预算和当前步骤
- `AgentStepRail` 展示 Think / Act / Observe / Decide 进度
- `MemoryContextPanel` 展示本次回答使用了哪些会话记忆、长期记忆和证据
- `SwarmRunPanel` 展示并行子 Agent 的目标、状态、结果和冲突
- 高风险工具卡片必须展示 gate 状态和确认/审批入口

## 9. 验收标准

- 用户输入“帮我完成这个 US 的质量闭环”时，系统能创建 `AgentGoal`，并按目标循环自主推进。
- 用户输入“并行分析这个版本所有未闭环 US 的风险”时，系统能创建 `AgentSwarmRun` 和多个 `AgentWorkerAssignment`。
- 任意 Agent 输出都能追溯到使用的记忆、上下文对象、工具调用和证据。
- 刷新页面或服务重启后，运行中的 `AgentGoal`、记忆摘要和 swarm 状态可恢复。
- 子 Agent 产出的冲突结论不会直接改正式状态，必须进入 `Merge/Score` 或审批链。
