# Nasus 后端总设计

## 1. 文档定位

本文是 Nasus 的后端实现总设计文档，用于统一收口 `agent-first + tool-native` 形态下的后端控制流、模块边界和实现主线。

优先级关系：

- 产品行为与默认规则以 [最终特性说明书](../../final-feature-spec.md) 为准。
- 本文定义后端总体结构与后端模块边界。
- 更细的对象、协议、接口、执行、运维细节，分别以下列文档为准：
  - [../platform/auth-and-access-design.md](../platform/auth-and-access-design.md)
  - [../agent/llm-runtime.md](../agent/llm-runtime.md)
  - [../agent/conversation-runtime.md](../agent/conversation-runtime.md)
  - [../agent/tool-catalog.md](../agent/tool-catalog.md)
  - [../system-image/context-engine.md](../system-image/context-engine.md)
  - [../quality-loop/quality-generation.md](../quality-loop/quality-generation.md)
  - [../platform/mcp-integration-design.md](../platform/mcp-integration-design.md)
  - [./domain-model.md](./domain-model.md)
  - [./runtime-and-tool-protocol.md](./runtime-and-tool-protocol.md)
  - [./api-and-events.md](./api-and-events.md)
  - [./execution-governance.md](./execution-governance.md)
  - [./ops-and-test-baseline.md](./ops-and-test-baseline.md)
  - [../agent/agent-loop-runtime.md](../agent/agent-loop-runtime.md)
  - [./end-to-end-flow-examples.md](./end-to-end-flow-examples.md)

## 2. 核心前提

- 平台采用 `agent-first` 形态，主会话是第一操作入口。
- 当前默认部署形态是“单企业内多项目平台”，不是公网 SaaS 多租户产品；租户边界默认等同于部署边界。
- 所有业务动作原生都必须支持 Agent 调用。
- 页面按钮、表单、快捷 chip、右侧卡片动作，都是同一套工具体系的不同触发入口。
- Agent 主体必须作为系统级 `Agent Service` 实现，负责目标、记忆、工具规划、Swarm 并行和结果收敛。
- 写操作的 canonical command surface 是 `ToolInvocation`。
- 读查询保留 read API，但正式业务动作不能只存在于 UI 表单流中。
- 高风险动作允许被 Agent 发起，但必须经过确认、审批或策略闸口。
- 正式事实对象不能由 Agent 直接写入，必须经过工具执行、merge 和 approval 主线推进。

## 3. 后端总体结构

### 3.1 技术栈

- `FastAPI`：会话入口、工具调用入口、对象查询、SSE 事件输出
- `OIDC / OAuth 2.1`：统一用户认证
- `SQLAlchemy 2 + Alembic`：对象持久化与 schema migration
- `Temporal`：长生命周期 workflow、审批等待、重试、恢复
- `LangGraph`：单任务内的 planning、tool routing、skill orchestration
- `LLM Gateway + Prompt Registry`：统一模型调用、Prompt 版本管理、token 预算和 Provider 路由
- `worker-runtime`：Context/Impact/Scenario/Failure 等 worker 池
- `runner`：Node.js/TypeScript + Playwright 的确定性执行层
- `PostgreSQL`：结构化事实源
- `MinIO`：原料、证据、执行产物
- `OpenGrok + Tree-sitter`：代码索引与解析

### 3.1.1 生产实现与本地 MVP 边界

当前仓库中可运行的本地实现只能作为 MVP 切片和交互验证参考，不是生产后端基线。

| 能力 | local / demo 允许 | prod 禁止 | prod 必须 |
| --- | --- | --- | --- |
| 数据库 | SQLite、临时 state dir | SQLite `create_all` 作为正式 schema | PostgreSQL + Alembic migration |
| 初始数据 | 手工 seed fixture | 服务启动自动 `_seed()` demo 数据 | 显式 fixture / migration / admin import |
| 状态存储 | singleton store、in-memory queue | 核心状态只在内存中 | 事务化 repository、outbox、恢复机制 |
| Workflow | local fallback | local runtime 作为正式长任务执行器 | Temporal 或等价 durable workflow |
| Graph runtime | local wrapper | LangGraph 只委托本地函数 | 真实 graph node、checkpoint、resume |
| SSE | 内存事件流 | 无 replay / heartbeat / Last-Event-ID | outbox + replay + entity_version |
| Auth | dev 模式固定开发用户；required 模式 Bearer Token 门禁 | 无权限校验或生产静默降级为开发用户 | OIDC / RBAC / PolicySnapshot；V1 过渡期至少启用 Bearer Token 门禁 |
| LLM | mock fallback | 生产默认 mock | Provider adapter、Prompt Registry、LLMCall audit |

任何生产代码合入前，必须证明没有依赖 demo seed、in-memory queue 或无迁移 schema。

### 3.2 后端逻辑分层

| 层 | 职责 |
| --- | --- |
| `Conversation Layer` | 接收主会话输入，理解意图，补足上下文，生成工具调用计划 |
| `Auth & Access Layer` | 身份认证、会话管理、角色绑定、API 鉴权 |
| `Agent Service Layer` | 管理 Agent 目标、记忆上下文、预算、并发、Swarm 和结果收敛 |
| `Tool Contract Layer` | 统一管理工具目录、工具调用、确认/审批闸口、策略检查 |
| `Workflow Layer` | 编排长生命周期业务流程，等待确认/审批，驱动跨阶段、跨请求恢复 |
| `Agent Loop Layer` | 承接用户高级目标的自主循环执行，Think → Act → Observe → Decide 持续推进 |
| `Agent Graph Layer` | 在 Agent Goal iteration 或单个工具内规划步骤、选择工具后的 Skill 路由、并行 Worker 调度 |
| `LLM Runtime Layer` | 管理 Provider、Prompt、上下文裁剪、预算与降级 |
| `Domain Materialization Layer` | 把工具结果物化为 `TaskContext`、`Run`、`MergedResolution` 等对象 |
| `Execution Layer` | 执行网页端动作，回传证据、状态和执行事件 |
| `Data & Audit Layer` | 存储对象、证据、审计事件、检索索引和同步检查点 |

### 3.3 首发模块结构

后端首发采用模块化单体，配套独立运行单元：

- `api/orchestrator`
- `workflow-service`
- `worker-runtime`
- `runner`

当前 `apps/api/app` 采用渐进式 DDD 分层迁移，不做一次性大搬家：

```text
apps/api/app/
  interface/
    http/                 # FastAPI router/controller，只做协议转换
    sse/                  # SSE envelope、outbox、streaming
  application/
    system_image/         # source/ingestion/context use case
    agent/                # conversation、goal、memory、swarm use case
    quality_loop/         # task、asset、run、release use case
    platform/             # auth、settings、audit、tool invocation use case
  domain/
    system_image/
    agent/
    quality_loop/
    platform/
    shared/
  infrastructure/
    persistence/
    llm/
    storage/
    workflow/
    runner/
  composition.py
```

准入规则：

- `main.py` 只保留应用创建和 `app` 暴露，具体路由挂载由 `composition.py` 组装。
- `interface/http/routers` 只处理 FastAPI 请求、响应、错误映射和 SSE envelope，不承载业务规则。
- `application/<domain>` 是新业务逻辑入口，跨模块调用只能通过 use case / port。
- `domain/<domain>` 只能包含纯领域对象、值对象、策略和状态机，禁止 import ORM、FastAPI、LLM、S3、Temporal。
- `infrastructure/*` 承载数据库、LLM、对象存储、workflow、runner 等适配器。
- `store.py` 当前仅允许承载迁移期 `RuntimeAssembly` 依赖组装与
  `ApplicationRuntime` compatibility facade；生产入口只能通过
  `get_runtime_assembly()` 获取唯一依赖图，再由 `ApplicationContainer`
  暴露 application services。不得向其中新增业务规则或创建第二套运行时状态。
- platform 支撑域优先迁移，因为 `ToolInvocation`、settings、audit、RBAC 和 gate 是 agent-first 写操作链路的基础。

### 3.4 服务间通信矩阵

| 来源 | 目标 | 通信方式 | 备注 |
| --- | --- | --- | --- |
| Frontend UI | `api/orchestrator` | REST + SSE | 主入口 |
| `api/orchestrator` | `workflow-service` | Temporal Client / Workflow Signal | 启动、恢复、取消 workflow |
| `workflow-service` | `worker-runtime` | 队列分发 `WorkerJob` | 队列产品可替换，协议固定 |
| `quality-loop application` | `runner` | authenticated internal HTTP | 提交结构化 Playwright steps；生产目标受 host allowlist 限制 |
| `worker-runtime` | `llm_gateway` | 内部 SDK / service call | 统一模型调用 |
| `api/orchestrator` | PostgreSQL / MinIO | ORM / object storage client | 将 Runner 原始 artifacts 物化为正式 Evidence；Runner 不直写领域事实 |

### 3.5 代码骨架建议

中长期可按应用与共享包继续拆分：

- `apps/api-orchestrator`
- `apps/workflow-service`
- `apps/worker-runtime`
- `apps/runner`
- `packages/domain`
- `packages/shared-contracts`
- `packages/llm-gateway`
- `packages/prompt-registry`
- `packages/context-engine`
- `packages/tool-registry`
- `packages/governance`
- `infra/docker`
- `infra/migrations`

默认约束：

- 每个 app 只有一个主入口和一个配置入口。
- 共享 schema、事件、对象引用协议都放在 `packages/shared-contracts`。
- Alembic migration 统一放在 `infra/migrations`。
- `docker-compose.yml`、本地启动脚本和示例环境变量应落在 `infra/docker` 与仓库根目录。
- 在拆出多服务前，模块化单体内部必须先满足上述 DDD 依赖方向；不能为了未来拆服务而保留当前大 `main.py`、大 `store.py`、大 repository 的无边界状态。

## 4. 控制流主线

### 4.1 主会话驱动链路

主链路从“API 调 service”调整为“会话 / UI -> Agent Service -> Tool/AgentGoal/Swarm -> workflow / service / worker -> 领域对象”：

1. 用户在主会话输入自然语言，或点击 UI 动作入口。
2. `Conversation Orchestrator` 读取上下文，理解意图，产出 `ToolInvocationPlan` 或 `AgentGoalProposal`。
3. 结构化 Planner 输出先经过 `AgentPlanPolicy`；只读确定性计划可由
   `Tool Invocation Runtime` 创建 `ToolInvocation`，包含写工具的计划必须提升为
   `AgentGoalProposal`。
4. 若是高级目标，则 `Agent Service` 创建 `AgentGoal`，通过 `Agent Memory Manager` 组装上下文，并在 `Temporal + LangGraph` 中持续推进。
5. 若目标复杂且可并行，则 `Agent Supervisor` 创建 `AgentSwarmRun` 和多个 `AgentWorkerAssignment`，并发执行子 Agent。
6. 工具调用先经过：
   - `context binding`
   - `policy check`
   - `confirmation / approval gate`
7. 工具执行期可进入：
   - `Temporal workflow`
   - `LangGraph` 内部 planning
   - `worker-runtime`
   - `runner`
8. 工具结果被物化为领域对象、候选决策或正式结论输入。
9. 所有动作都写入 `AuditEvent`，并关联 `conversation_id + tool_invocation_id + task_id + run_id`；Agent 自驱链路还需关联 `agent_goal_id + agent_step_id`，Swarm 链路还需关联 `swarm_run_id + assignment_id`。

### 4.2 UI 与会话双轨

- `chat` 是第一入口，但不是唯一入口。
- `ui`、`api` 仍可直接触发动作。
- 所有这些动作都必须先形成 `ToolInvocation`。
- 因此：
  - 同一个“生成测试场景”动作，从 chat 和 button 触发，必须写入同类 `ToolInvocation`
  - 同一个“查看当前测试进度”动作，从 query card 和 chat 触发，必须调用同一类查询工具

## 5. 关键后端组件

| 组件 | 作用 |
| --- | --- |
| `Conversation Orchestrator` | 将自然语言转成 `ClarificationRequest / DirectAnswer / ToolInvocationPlan / AgentGoalProposal`；UI 动作直接使用同一工具契约 |
| `Agent Service / Supervisor` | 管理 `AgentGoal`、自主级别、预算、目标拆分、Swarm 并行和执行策略 |
| `Agent Memory Manager` | 为 LLM 调用组装短期记忆、会话记忆、长期系统画像和候选知识 |
| `Agent Swarm Coordinator` | 创建并调度多个 `AgentWorkerAssignment`，并把候选结果交给 Merge/Score |
| `AuthMiddleware / AccessMiddleware` | 校验身份、会话、角色与策略 |
| `Tool Registry` | 维护 `ToolDefinition`，声明风险、确认方式、输入输出 schema、产物对象 |
| `Tool Invocation Runtime` | 统一执行业务动作，做 context binding、policy gate、approval gate、result materialization |
| `Confirmation / Approval Gate` | 承接高风险动作的确认和审批等待 |
| `Agent Loop Runtime` | 承接 Agent 自驱目标的持续循环执行，每步自主选择工具并根据结果动态调整 |
| `Central Orchestrator Agent` | 负责中心侧 planning、工具选择和候选结论生成 |
| `LLM Gateway` | 统一模型路由、Prompt 选择、token 预算、重试和降级 |
| `Skill Registry` | 工具背后的内部能力目录 |
| `Worker Runtime` | 具体执行 Context/Impact/Scenario/Failure 等 worker |
| `Merge / Score` | 合并中心端候选结果与结构化冲突输入，生成 `MergedResolution` 建议 |
| `Approval Control` | 推进正式知识晋级、放行结论和基线回写 |

## 6. 正式事实边界

后端必须写死以下边界：

- `Run` 是唯一正式执行对象。
- `ToolInvocation` 是命令记录，不是正式领域结论。
- `AgentDecision` 是候选决策，不是正式领域结论。
- `MergedResolution` 才能推进正式任务状态、正式放行结论和正式知识结论。
- `Candidate Knowledge -> Version Shared -> Official Baseline` 的晋级必须通过审批链完成。
- `pending_merge` 适用于任务、执行、知识三类冲突对象。

## 7. 交付顺序

后端开发前，先完成以下规格：

1. `design/backend/domain-model`
2. `design/backend/runtime-and-tool-protocol`
3. `design/backend/api-and-events`
4. `design/backend/execution-governance`
5. `design/backend/ops-and-test-baseline`
6. `design/platform/auth-and-access-design`
7. `design/agent/llm-runtime`
8. `design/agent/conversation-runtime`
9. `design/agent/tool-catalog`
10. `design/agent/agent-loop-runtime`
11. `design/system-image/context-engine`
12. `design/quality-loop/quality-generation`
13. `design/platform/mcp-integration-design`
14. `design/backend/end-to-end-flow-examples`

完成后再进入代码实现，避免开发过程中继续回到产品层做核心决策。
