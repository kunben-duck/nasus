# Nasus Conversation Orchestrator 设计

## 1. 文档定位

本文展开 `Conversation Orchestrator` 的内部设计，解决“自然语言输入如何变成 `ToolInvocationPlan`”这一核心黑盒。

## 2. 组件职责

`Conversation Orchestrator` 只做 4 件事：

- 理解用户输入
- 绑定当前空间上下文
- 生成 `ToolInvocationPlan`
- 判断是否需要澄清、确认或直接执行

它不直接：

- 改正式领域状态
- 绕过工具层执行
- 长时间等待审批或执行完成

## 3. 输入

每次会话输入最小上下文：

- `conversation_id`
- `space_type`
- `space_id`
- `project_id`
- `version_id`
- `session_id`
- `us_id` 可空
- `task_id` 可空
- `latest_messages`
- `visible_context_refs`
- `actor_ref`
- `role_set`

## 4. 输出

`Conversation Orchestrator` 固定只产出 4 类结果之一：

- `ClarificationRequest`
- `ToolInvocationPlan`
- `DirectAnswer`
- `AgentGoalProposal`

约束：

- 只要问题能落到现有工具目录，就优先产出 `ToolInvocationPlan` 或 `AgentGoalProposal`
- 只读型、低风险、无需长流程的查询可以产出 `DirectAnswer`
- 缺上下文或意图歧义时，必须先产出 `ClarificationRequest`
- 高级目标、需要动态多步推进的请求，必须产出 `AgentGoalProposal`

## 5. 内部处理流程

### 5.1 五阶段管线

1. `Normalize`
   - 规范输入文本、附件引用、上下文选择
2. `Bind Context`
   - 解析当前项目、版本、US、任务、设备状态
3. `Classify Intent`
   - 判断是查询、创建、分析、执行、治理、同步还是澄清
4. `Plan Action`
   - 选择一个或多个工具，补足输入参数，确定执行顺序
5. `Emit`
   - 输出 `ClarificationRequest / ToolInvocationPlan / DirectAnswer / AgentGoalProposal`

### 5.2 决策规则

- 若用户输入“查看当前测试进度”
  - 分类为 `query`
  - 优先选择 `Query / Insight Tool`
- 若用户输入“帮我创建版本并导入 US”
  - 分类为 `multi-step version operation`
  - 产出多步 `ToolInvocationPlan`
- 若用户输入“帮我完成这个 US 的质量闭环”
  - 分类为 `agent_goal`
  - 产出 `AgentGoalProposal`
- 若用户输入缺少关键上下文
  - 先发 `ClarificationRequest`
- 若用户输入包含高风险治理动作
  - 仍可生成计划
  - 但必须标注后续会进入 `waiting_confirmation / waiting_approval`

## 6. ToolInvocationPlan 结构

最小字段：

- `plan_id`
- `conversation_id`
- `intent_kind`
- `confidence`
- `required_clarifications`
- `steps`
- `recommended_next_tools`

### 6.1 AgentGoalProposal 结构

最小字段：

- `goal_template` 可空
- `goal_description`
- `suggested_autonomy_level`
- `estimated_steps`
- `estimated_duration`
- `target_refs`
- `requires_user_confirmation`

每个 `step` 最小字段：

- `step_id`
- `tool_id`
- `target_scope`
- `input_payload`
- `depends_on`
- `gate_expectation`

## 7. 澄清策略

只有以下情况才应该先澄清：

- 缺少必要上下文，例如版本或项目未选择
- 多个工具候选且风险差异明显
- 高风险动作影响范围过大
- 输入意图冲突

不得在以下情况滥用澄清：

- 已有足够上下文可直接查询
- 只是参数可由当前上下文补齐
- 只是轻微歧义但不会影响低风险只读结果

## 8. 与 Tool Runtime、Temporal、LangGraph 的边界

- `Conversation Orchestrator`
  - 负责生成计划或提出 `AgentGoalProposal`
- `Tool Invocation Runtime`
  - 负责执行计划中的 step
- `Temporal`
  - 负责长生命周期和等待节点
- `LangGraph`
  - 负责单个工具内部的 planning、skill routing、worker orchestration

即：

`Conversation Orchestrator` 解决“接下来做什么”
`LangGraph` 解决“Agent Loop 或工具内部具体怎么做”

## 8.1 与 Agent Loop、LLM Runtime 的衔接

- `Conversation Orchestrator` 先做意图分类：
  - 低风险只读查询 -> `DirectAnswer`
  - 单步或多步确定性动作 -> `ToolInvocationPlan`
  - 需要持续自主推进的高级目标 -> 交给 `Agent Loop Runtime`
- 意图分类默认优先使用 `structured` 模型输出，不直接依赖自由文本 function calling。
- 当问题被提升为 `AgentGoal` 时：
  - Orchestrator 只负责创建 `goal_description + initial context`
  - 后续 `THINK/ACT/OBSERVE/DECIDE` 交给 [docs/agent-loop-runtime.md](/Users/uben/project/project/Nasus/docs/agent-loop-runtime.md)
- Tool 选择遵循“先规则过滤，再由结构化模型排序”的路线：
  - 规则过滤：空间、角色、risk、required_context
  - 结构化模型排序：从候选工具中选最合适工具

## 9. 结果回写

每次会话输入都必须留下：

- `conversation.message.created`
- 可选的 `conversation.plan.updated`
- 可选的 `conversation.agent_goal.proposed`
- 如执行工具，则创建 `ToolInvocation`

`Conversation Orchestrator` 自身不写 `Task / Run / MergedResolution`。

## 10. 失败与降级

若会话规划失败，按以下顺序处理：

1. 重试意图分类
2. 切换结构化输出模型
3. 降级到只读回答
4. 让用户缩小问题范围

规划失败不应直接导致整个业务 workflow 失败。
