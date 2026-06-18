# Nasus 技术方案设计基线

## 1. 文档定位

本文是 Nasus 当前需求集的技术方案设计基线。

它回答：

- 当前需求是否已有技术方案承接
- 哪些设计已经成熟，可以进入开发
- 哪些方案仍属于 P0 开发前必须冻结的技术契约
- 第一个生产可用版本应该按什么纵切顺序落地
- 现有文档之间的冲突如何收敛

本文不替代模块级与实现级细节文档。更细的对象、接口、运行时、页面和测试规则仍以对应文档为准。

## 2. Agent Team 审视结论

本轮按 5 个角色审视当前文档和实现：

- PM：产品需求、范围、用户旅程、验收标准
- 架构师：整体系统架构、模块依赖、运行时和治理边界
- 前端负责人：Web Portal、AI Studio 风格、agent-first 交互、SSE 状态同步
- 后端负责人：Tool-first、AgentGoal、系统画像、质量闭环、持久化和事件
- QA 负责人：测试金字塔、阶段门禁、生产验收链路

共同结论：

- 产品定位正确：Nasus 是 agent-first 的质量闭环平台，不是通用聊天系统，也不是单纯测试用例生成器。
- 三大产品模块正确：系统画像构建、Agent 主体、质量闭环主体。
- 架构主线正确：`Conversation / UI -> Agent Service / ToolInvocation -> Workflow / Worker / Runner -> Domain Object -> Evidence / Approval`。
- 当前文档已经能说明方向，但还需要一个开发基线把 P0 范围、技术边界、准入门槛和验收方式冻结。
- 当前代码只能作为可运行 MVP 切片参考，不是生产实现基线；生产实现必须按本文约束重构或替换。

## 3. 第一个生产可用版本的 P0 纵切

P0 不是演示版，也不是全量长期愿景。P0 固定为一条能真实判断单个版本是否可上线的纵切：

```text
项目创建
  -> 三源接入
  -> 系统画像 ready
  -> Official Baseline
  -> Version fork
  -> US 导入与分配
  -> TaskContext
  -> QualityProfile
  -> QualityAssetPack
  -> AutomationBlueprint
  -> Run / Evidence
  -> FailureReport
  -> Release Readiness
  -> Approval / ReleaseDecision
  -> Baseline Promotion
```

P0 必须包含：

- Web Portal 作为唯一正式入口。
- 三源一等 source：代码、历史 US 文档、历史测试用例和自动化脚本。
- 主会话和 UI 动作全部进入 ToolInvocation。
- AgentGoal 支持 pause / resume / gate / audit。
- 系统画像能生成 `US -> code -> tests` 可追溯关系。
- 系统画像检索链路必须包含 PostgreSQL FTS、pgvector embedding、hybrid retrieval、rerank adapter 和降级记录。
- TaskContext 和 QualityProfile 是质量生成前置条件。
- QualityAssetPack 支持 revision、review、局部重生成和 pending_merge。
- Run 和 ExecutionEvidence append-only。
- FailureReport 和基础 HealingProposal。
- Release Readiness 和正式 ReleaseDecision。
- approval、resolution.merge、baseline.promote 的治理 gate。
- 统一审计链：`conversation -> agent goal -> tool invocation -> domain object -> evidence -> approval`。
- 生产非功能门禁：Auth/RBAC、PostgreSQL/Alembic、SSE replay/outbox、密钥保护、CI、备份和可观测性。

P0 不包含：

- Desktop / Edge 本地执行体系。
- 公网 SaaS 多租户。
- UX / OpenAPI / 缺陷 / 执行日志的深度自动接入。
- 大规模外部插件市场。
- 完整 Neo4j / OpenSearch / Weaviate / Qdrant 独立集群投影。

说明：P0 不要求独立检索集群，但要求 V1 在 PostgreSQL + pgvector 上落地长期检索架构的最小实现，包括 embedding、hybrid retrieval、rerank adapter、检索运行记录和可替换 adapter 边界。

## 4. 三大产品模块与技术实现关系

| 产品模块 | 技术实现主线 | 必须产物 |
| --- | --- | --- |
| 系统画像构建模块 | Source Connector、RawAsset、ContextObject、Baseline、Embedding、Hybrid Retrieval、Rerank、Quality Context | `TaskContext`、`QualityProfile`、`RegressionProfile`、`CoverageMatrix` |
| Agent 主体模块 | Conversation、AgentGoal、Memory、ToolInvocation、Swarm、LLM Runtime | `ToolInvocationPlan`、`AgentStep`、`AgentDecision`、`AuditEvent` |
| 质量闭环主体模块 | Verification、Scenario、Case、Automation、Run、Failure、Release、Approval | `QualityAssetPack`、`Run`、`Evidence`、`FailureReport`、`ReleaseDecision` |

实现原则：

- 系统画像不能只是检索库，必须成为质量上下文控制层。
- Agent 不能直接写正式事实，只能通过工具、候选结果、merge 和 approval 推进。
- 质量闭环不能绕过系统画像直接从 US 文本自由生成。
- UI 不能绕过 ToolInvocation 直接修改正式领域对象。

## 5. 关键技术决策

### 5.1 Command Boundary

写操作的 canonical entry 是 `POST /v1/tool-invocations`。

领域写接口允许存在，但分为两类：

- 外部可调用写入口：必须创建或绑定 `tool_invocation_id`，并走 policy / gate / audit。
- 内部领域写口：只能由 ToolInvocationRuntime、Workflow、Domain Materialization Layer 调用。

禁止：

- UI button 直接写正式领域对象。
- Agent 输出文本直接成为正式结论。
- domain service 绕过 audit 写 Official Baseline。

### 5.2 Shared Contracts

P0 开发前必须冻结共享契约：

- 对象 schema：Project、SourceBinding、RawAssetRecord、ContextObject、TaskContext、QualityProfile、QualityAssetPack、Run、Evidence、Approval、ReleaseDecision。
- 事件 schema：Conversation、AgentGoal、AgentStep、ToolInvocation、Task、Run、Approval、Release、SSE envelope。
- 状态机：SystemImage、ToolInvocation、AgentGoal、TaskContext、QualityAssetPack、Run、MergedResolution、ReleaseDecision。
- 错误响应：统一 `request_id / timestamp / error.code / error.message / details / retry_after`。
- 幂等：所有写操作必须支持 `Idempotency-Key` 或等价内部幂等键。

### 5.3 Workflow / Eventing / Recovery

生产链路必须采用 durable runtime。

- Temporal 或等价 workflow 是长生命周期任务真相源。
- PostgreSQL 是正式事实和 read model 真相源。
- SSE 通过 outbox 派发，不允许只依赖内存队列。
- SSE 支持 `Last-Event-ID`、heartbeat、replay、dedupe、entity_version。
- Workflow 重启后必须能恢复 AgentGoal、ToolInvocation、Approval 和 Run 状态。

local fallback 只允许用于本地开发和测试，不能作为生产实现路径。

### 5.4 System Image Quality Context

系统画像必须提供质量闭环可直接消费的结构化上下文：

- `TaskContext`：当前 US、验收标准、影响对象、历史 US、历史测试资产、缺失上下文。
- `QualityProfile`：风险、验证策略、回归范围、自动化适配度、证据要求。
- `RegressionProfile`：直接影响、间接影响、必须回归、建议回归、排除项和风险理由。
- `CoverageMatrix`：`AcceptanceCriteria -> VerificationPoint -> Scenario -> TestCase -> AutomationScript -> Run -> Evidence`。

这些对象必须带：

- `source_refs`
- `confidence`
- `freshness_at`
- `baseline_id / overlay_id`
- `context_hash`
- `stale_reason`

### 5.5 Frontend Production Baseline

正式前端必须满足：

- `App -> RouterProvider -> real pages`，禁止正式入口继续依赖 `PrototypeStudio` 或 state-only 路由。
- 使用 `TopLevelStudioShell` 和 `ProjectWorkspaceShell` 两套壳层。
- Google AI Studio 风格和 `ux/` 高保真原型必须转成设计 token、组件和状态模型。
- 所有 button / chip / card action 进入 Action Registry，再映射到 ToolInvocation。
- SSE 由 typed EventReducer 和 MessageStreamAssembler 消费，不得只做全量 invalidate。
- Agent UI 必须包含 AgentGoalCard、AgentStepRail、ThinkingCard、GateCard、ToolInvocationTimeline、MemoryContextPanel、SwarmRunPanel。
- Personal Workspace 必须展示 TaskContext、QualityProfile、QualityAssetPack、Run settings、Evidence 和 Policy。

### 5.6 Backend Production Baseline

正式后端必须满足：

- PostgreSQL + Alembic 是生产默认，不允许生产使用 SQLite `create_all`。
- 禁止生产启动时自动 `_seed()` demo 数据。
- 禁止把核心对象长期存成 JSON blob；AgentStep、ToolResult、QualityAssetPack part、Evidence、PolicySnapshot、LLMCall 必须有正式结构。
- Tool Catalog 与 ToolInvocationRuntime 必须覆盖 P0 最小工具集。
- OIDC / RBAC / PolicySnapshot / ApprovalWorkflow 必须进入写链路。
- LLM 调用必须经过 Prompt Registry、provider adapter、structured output validation、token budget 和 LLMCall audit。
- Runner 必须使用隔离环境、短期凭证、secret redaction 和 evidence artifact 管理。

### 5.7 Governance Baseline

正式事实边界：

- `AgentDecision` 是候选，不是正式结论。
- `MergedResolution` 是冲突收敛结果。
- `ReleaseAdvice` 是建议，不是正式放行。
- `ReleaseDecision` 是正式放行记录，必须经 policy / approval / audit。
- `baseline.promote` 是 critical 工具，必须同时满足确认、审批、证据完整和权限策略。

## 6. P0 Tool Catalog 最小集

P0 至少实现以下工具，并全部进入 `GET /v1/tools/catalog`：

- `project.create`
- `project.assets.connect`
- `system_image.sources.register`
- `system_image.sources.ingest`
- `system_image.context.materialize`
- `system_image.baseline.initialize`
- `project.status.get`
- `version.create`
- `version.inputs.import`
- `version.branch.bind`
- `version.participants.assign`
- `version.risk.initialize`
- `version.progress.get`
- `us.task.start`
- `quality.scope.generate`
- `quality.scenario.generate`
- `quality.case.generate`
- `quality.asset-pack.refresh`
- `automation.generate`
- `run.start`
- `run.progress.get`
- `failure.analyze`
- `release.advice.get`
- `approval.request`
- `resolution.merge`
- `release.decision.submit`
- `baseline.promote`
- `progress.get`
- `risk.summary.get`
- `system-image.inspect`
- `conflicts.get`

所有工具必须声明：

- `tool_id`
- `risk_level`
- `confirmation_mode`
- `required_context`
- `input_schema_ref`
- `output_schema_ref`
- `produced_objects`
- `owner_service`
- `workflow_binding`
- `events_emitted`

## 7. 开发落地顺序

### 7.1 Phase 0：技术契约冻结

交付：

- shared contracts
- canonical Tool Catalog
- command boundary
- state machines
- SSE envelope
- error envelope
- P0 acceptance matrix

验收：

- 所有 P0 对象、事件、工具、状态机可被测试引用。
- 文档中不存在同一工具多命名或同一接口多语义。

### 7.2 Phase 1：平台底座

交付：

- Auth / RBAC / PolicySnapshot
- PostgreSQL / Alembic
- AuditEvent
- ToolInvocationRuntime
- SSE outbox / replay
- LLM provider settings and LLMCall audit

验收：

- 未授权写操作被拒绝。
- UI / chat / API 触发同一动作产生同类 ToolInvocation。
- 服务重启后事件和状态可恢复。

### 7.3 Phase 2：系统画像首切片

交付：

- 三源 source slot
- source register / ingest
- RawAssetChunk 切块
- EmbeddingRecord 生成与 stale 管理
- PostgreSQL FTS + pgvector hybrid retrieval
- RerankService adapter + rule-based fallback
- RetrievalRun / RerankRecord 审计
- ContextObject / ContextRelationship
- Official Baseline
- TaskContext / QualityProfile

验收：

- 缺三源时 AgentGoal pause。
- 三源齐全时生成可追溯 `US -> code -> tests` 图谱。
- 相似 US、相似测试用例和相似失败模式可通过 hybrid retrieval 召回，并经过 rerank 或 fallback fusion 后进入 TaskContext。
- embedding 模型版本变化或 source 内容 hash 变化时，相关 `EmbeddingRecord` 进入 `stale` 并可重建。
- rerank provider 不可用时系统降级为 rule-based fusion，并写入检索运行记录。
- 失败 source 不污染 Official Baseline。

### 7.4 Phase 3：Agent 主体

交付：

- Conversation Orchestrator
- AgentGoal state machine
- AgentStep streaming
- Memory Manager
- Tool planning
- pause / resume / interrupt
- Swarm candidate result

验收：

- Agent 能从主会话规划多工具目标。
- gate 后能恢复原 AgentGoal。
- 子 Agent 只产出候选，不直接写正式事实。

### 7.5 Phase 4：质量闭环

交付：

- VerificationPoint
- Scenario / Case
- CoverageMatrix
- QualityAssetPack revision
- AutomationBlueprint
- Run / Evidence
- FailureReport / HealingProposal

验收：

- TaskContext / QualityProfile 未 ready 时禁止质量生成。
- 每个 must 验证点至少有测试用例。
- Evidence 可回溯到 Run、ToolInvocation、US 和系统画像对象。

### 7.6 Phase 5：治理与放行

交付：

- pending_merge
- MergedResolution
- ApprovalWorkflow
- ReleaseAdvice
- ReleaseDecision
- Baseline Promotion

验收：

- 高风险动作进入 confirmation 或 approval。
- ReleaseDecision 可解释且可审计。
- Baseline Promotion 只能在审批通过后执行。

### 7.7 Phase 6：生产硬化

交付：

- CI gates
- observability
- backup / restore
- runner isolation
- fault injection
- SLO and runbooks

验收：

- PR、integration、staging、release 各阶段门禁明确。
- workflow replay、SSE replay、故障恢复、权限负测通过。

## 8. 测试与验收门禁

### 8.1 测试金字塔

| 层级 | 内容 | 目标 |
| --- | --- | --- |
| L0 静态与契约 | typecheck、lint、OpenAPI、SSE schema、Tool Catalog | 防止契约漂移 |
| L1 单元 | 状态机、policy、gate、source parser、SSE reducer | 防止局部逻辑错误 |
| L2 服务集成 | ToolInvocation、AgentGoal、系统画像、质量闭环 | 验证服务边界 |
| L3 消费者契约 | 后端事件与前端 reducer、ToolResult、Evidence | 验证前后端兼容 |
| L4 E2E | Build、Dashboard、Personal Workspace、Release | 验证用户旅程 |
| L5 故障注入 | worker crash、runner timeout、approval wait、healing loop | 验证生产韧性 |

### 8.2 首批必须自动化的验收用例

- 三源缺失时 AgentGoal pause，不能初始化 Official Baseline。
- 三源齐全时完成 register / ingest / materialize / baseline confirm。
- source 失败时 materialize 和 baseline 初始化被阻断。
- 创建 version、导入 US、生成 TaskContext 和 QualityProfile。
- 缺失或 stale TaskContext 时禁止质量生成。
- 生成 scope / scenario / case，并闭合 CoverageMatrix。
- 生成 AutomationBlueprint 后 `run.start` 产出 Run 和 append-only Evidence。
- failed Run 生成 FailureReport。
- 重复 failure fingerprint 或 max healing depth 触发 fallback-to-human。
- Release Readiness 聚合 US、资产、Run、Evidence、Approval 和 pending_merge。
- approval、resolution.merge、baseline.promote 必须进入 gate。
- SSE 事件重复、乱序、断线恢复后前端状态仍能收敛。

## 9. 文档优化结论

当前文档体系不是推倒重来，而是按本文进行收敛：

- [产品需求基线](./product-requirements.md)：冻结 P0/P1 范围和生产验收。
- [系统架构与部署设计](./system-architecture.md)：保持三大模块和七层架构主线。
- [实现总览](./implementation-overview.md)：保持跨模块开发顺序和前后端映射。
- [后端总设计](./design/backend/system-design.md)：补生产实现禁用项和真实运行时要求。
- [后端 API 与事件契约](./design/backend/api-and-events.md)：对齐事件命名、SSE replay、幂等和 response envelope。
- [Tool Catalog](./design/agent/tool-catalog.md)：作为唯一工具命名来源。
- [Portal 前端架构](./design/frontend/portal-architecture.md)：补生产入口、Action Registry、SSE reducer 和 Agent UI 准入。
- [后端运维与测试基线](./design/backend/ops-and-test-baseline.md)：补阶段质量门禁。

## 10. 开发准入判断

当前可以进入开发，但只能按本文的 Phase 0 开始。

不得直接进入大规模业务开发，直到以下设计冻结：

- P0 Tool Catalog
- shared contracts
- command boundary
- production persistence baseline
- SSE eventing / recovery
- Auth / RBAC / PolicySnapshot
- frontend RouterProvider / action registry baseline
- P0 acceptance matrix

冻结后，开发应按纵切推进，而不是按前端、后端、Agent、系统画像各自孤立推进。
