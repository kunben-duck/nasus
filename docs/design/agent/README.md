# Agent 主体模块

## 1. 模块目标

Agent 主体模块是 Nasus 的中枢模块。它不是普通聊天入口，而是整个系统的 `Agent Service`：负责主会话、工具计划、自主循环、模型调用、多层记忆和多 Agent 并行协作。

从产品形态看，Nasus 是一个大的 agent-first 质量闭环服务。系统画像构建、质量闭环、执行、治理和查询都必须作为工具能力被 Agent 原生调用；用户可以通过按钮完成任务，也可以通过主会话把同一件事交给 Agent 自主规划和推进。

正式需求、AgentGoal/AgentStep、记忆、工具调用、Swarm、事件流和验收标准以 [产品需求基线：Agent 主体模块需求](../../product-requirements.md#6-agent-主体模块需求) 为准。

## 2. 模块边界

负责：

- `Conversation Orchestrator`
- `Conversation Session / Message`
- `ToolInvocationPlan`
- `Agent Service / Agent Supervisor`
- `AgentGoal`
- `Agent Memory Manager`
- `Agent Swarm Coordinator`
- `LLM Gateway`

不负责：

- 正式领域结论落库
- 审批最终裁决
- 直接绕过工具层修改领域对象

## 3. 前端组成

- 顶层会话区
- `ChatTimeline`
- `AgentGoalCard`
- `ThinkingCard`
- `MemoryContextPanel`
- `SwarmRunPanel`
- `InterruptControls`

## 4. 关键对象与能力

### 4.1 主要对象

- `ConversationSession`
- `ConversationMessage`
- `ConversationSummaryCheckpoint`
- `SessionKnowledgeBinding`
- `ToolInvocation`
- `AgentGoal`
- `AgentStep`
- `AgentMemoryItem`
- `AgentSwarmRun`
- `AgentWorkerAssignment`

### 4.2 子文档

- [会话运行时设计](./conversation-runtime.md)
- [Agent Service、记忆与蜂群模式设计](./agent-service-memory-and-swarm.md)
- [Agent Loop Runtime](./agent-loop-runtime.md)
- [LLM 运行时设计](./llm-runtime.md)
- [Tool Catalog](./tool-catalog.md)

## 5. 开发指导

- 所有主会话输入必须优先进入 `Conversation Orchestrator`。
- 普通查询也应尽量走 `ToolInvocationPlan`，而不是散落在前端关键词路由里。
- 长对话必须通过 `summary checkpoint + recent messages + visible context refs` 组装上下文窗口。
- 所有 LLM 调用前必须经过 `Agent Memory Manager` 组装上下文，不能由页面或单个业务服务随意拼接 prompt。
- 复杂目标允许由 `Agent Supervisor` 拆分为 `AgentSwarmRun`，并行调度多个 worker agent，但每个子 Agent 仍只能通过 `ToolInvocation` 执行动作。
- 任何 Agent 行为都不得绕过 `ToolInvocation` 和策略闸口。

## 6. 验收标准

- 主会话能稳定产出 `ClarificationRequest / DirectAnswer / ToolInvocationPlan / AgentGoalProposal`
- Agent Goal 支持真正的 `pause / resume / feedback / continue`
- 多轮对话存在可感知的会话记忆，而不是单轮 mock 回复
- 用户能查看本次 Agent 回答使用的短期记忆、会话摘要、长期系统画像和证据引用
- 复杂任务可以创建 `AgentSwarmRun`，并行执行多个子 Agent 任务，结果进入合并与治理链路
- 每个 Agent 动作都能追溯到 `AgentGoal -> AgentStep -> ToolInvocation -> ToolResult -> AuditEvent`
