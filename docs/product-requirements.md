# Nasus 产品需求基线

## 1. 文档定位

本文是 Nasus 首个正式版本的产品需求基线，负责把项目计划、最终特性说明、模块设计和实现文档中的需求收敛为可开发、可验收的需求说明。

本文回答：

- 首个正式版本要交付什么
- 三大产品模块各自承担什么需求
- 哪些能力必须进入 V1，哪些能力延后
- 每个模块的输入、输出、状态、阻断和验收标准是什么

本文不展开数据库表、API 细节、前端组件实现、模型 prompt 或部署拓扑。这些内容分别由架构和实现文档承接。

当前所有需求对应的技术方案、生产准入、P0 纵切和开发顺序以 [技术方案设计基线](./technical-solution-baseline.md) 为准。

## 2. 产品目标

Nasus 的核心目标是帮助团队判断：

> 这次变更是否真的准备好上线。

首个正式版本必须围绕一条真实质量闭环交付，而不是堆叠零散功能。目标链路固定为：

`项目创建 -> 三源接入 -> 系统画像初始化 -> 版本创建 -> US 质量闭环 -> 执行证据 -> 失败归因 -> 放行建议 -> 知识沉淀`

Nasus 是 agent-first 产品，但不是通用聊天系统。Agent 的职责是理解目标、补齐上下文、规划步骤、调用工具和收敛结果；正式事实、审批、执行证据和基线回写必须由确定性领域链路完成。

## 3. 首个正式版本范围

### 3.1 必须交付

- Web Portal 作为唯一正式工作入口。
- Build / Dashboard / Project Space / Version Space / Personal Workspace / Runs / Governance 作为核心工作空间。
- 三类一等 source 接入：代码、历史 US 文档、历史测试用例和自动化脚本。
- 系统画像初始化，并形成项目 Official Baseline。
- 版本从 Official Baseline fork 出 Version Working Baseline。
- US 导入、分配、风险初始化和闭环状态追踪。
- Agent 主会话驱动项目接入、系统画像、版本、US 质量闭环和查询。
- ToolInvocation 作为所有写动作的 canonical command surface。
- 单个 US 的 TaskContext、QualityProfile、QualityAssetPack、Run、Evidence、FailureReport 和 ReleaseAdvice。
- 高风险动作的确认或审批 gate。
- 审计链路能追溯 `conversation -> agent goal -> tool invocation -> domain object -> evidence -> approval`。

### 3.2 V1 可延后

- Desktop / Edge 本地执行体系。
- 公网 SaaS 多租户能力。
- 通用代码生成平台能力。
- 通用测试管理系统的全量替代能力。
- 大规模企业插件市场。
- UX、OpenAPI、缺陷系统、执行日志的深度自动接入。
- 完整 Neo4j / OpenSearch 独立集群投影。

### 3.3 V1 不允许

- 在真实 source 缺失时静默用默认占位 source 初始化正式系统画像。
- UI 按钮绕过 ToolInvocation 直接写正式领域对象。
- Agent 直接写 Official Baseline、正式放行结论或审批结果。
- Agent 输出的临时文本被当作正式质量结论。
- 质量闭环退化为单纯测试用例生成。

## 4. 角色与核心旅程

### 4.1 角色

| 角色 | 关键需求 |
| --- | --- |
| 平台管理员 | 创建项目、绑定 source、初始化系统画像、管理 Official Baseline 和策略 |
| 版本负责人 | 创建版本、导入 US、绑定变更范围、分配参与者、推动版本收口 |
| 质量负责人 | 审核质量资产、确认执行证据、判断版本风险和放行准备度 |
| 质量参与者 | 围绕单个 US 完成分析、生成、执行、归因和总结 |
| 审批者 / 发布负责人 | 审批放行、知识晋级和基线回写 |
| Agent | 通过工具规划和推进任务，不能绕过治理或正式事实边界 |

### 4.2 端到端旅程

1. 管理员在 Build 创建项目。
2. Agent 引导补充代码、历史 US 文档、历史测试资产。
3. 系统摄入三类 source，抽取对象、关系和指标。
4. 管理员确认后初始化 Official Baseline。
5. 版本负责人创建版本，系统 fork Version Working Baseline。
6. 版本负责人导入 US、绑定开发分支或变更范围、分配负责人。
7. 质量参与者进入 Personal Workspace，启动 US 质量闭环。
8. Agent 基于系统画像生成 TaskContext、QualityProfile 和质量资产草案。
9. 用户审核并局部重生成质量资产。
10. 系统生成或绑定自动化脚本，触发 Run，收集 Evidence。
11. 执行失败时系统生成 FailureReport 和 HealingProposal。
12. 版本级 Release Readiness 汇总 US、Run、Evidence、Approval 和未闭环项。
13. 审批通过后，候选知识进入 Version Shared，再按治理回写 Official Baseline。

## 5. 系统画像构建模块需求

### 5.1 模块目标

系统画像构建模块负责把分散的项目知识转成可长期维护、可基线化、可被 Agent 和质量闭环消费的统一上下文。

它不是代码搜索库，也不是一次性知识库。它必须持续维护“代码、US、测试资产”之间的质量关系。

系统画像到质量闭环的转换规则，包括验证点识别、测试用例构建、自动化蓝图、运行回归、上线判断和历史功能保护，以 [系统画像长期质量闭环支撑方案](./design/system-image/quality-closure-enablement.md) 为准。

### 5.2 V1 输入范围

| Source | V1 要求 | 延后能力 |
| --- | --- | --- |
| 代码 | Git URL、本地仓库路径、分支、commit、目录过滤、文件 hash、语言识别、符号抽取 | 深度 blame、跨仓库依赖、全量安全扫描 |
| 历史 US 文档 | Markdown、TXT、可抽文本的 DOCX/PDF、US 编号、标题、验收标准、流程和风险词 | 复杂版式理解、外部需求系统双向同步 |
| 历史测试资产 | 测试用例文档、Playwright/Cypress/Jest/Pytest 等脚本、测试名、断言、页面/API 调用 | 完整测试管理平台同步、非 Web 专项工具 |

增强 source 如 OpenAPI、UX、缺陷和执行日志可以作为补充输入，但不得成为 V1 主链路的前置依赖。

### 5.3 Source 绑定需求

- 用户可以通过 UI 或主会话绑定三类 source。
- Agent 必须能识别缺失 source，并追问代码、US 文档和测试资产的位置。
- 缺少真实 source 时，只能创建 source slots，并返回 `requires_followup=true`。
- 缺少真实 source 时，不得执行正式摄入、物化画像或初始化 Official Baseline。
- Source 绑定必须记录来源、触发者、时间、凭据引用、hash、权限校验结果和失败原因。

### 5.4 生命周期

系统画像状态固定为：

`draft -> source_required -> ingesting -> partially_failed -> materialized -> pending_review -> ready -> stale`

状态规则：

- `source_required` 表示缺少一等 source，AgentGoal 必须暂停等待补充。
- `partially_failed` 表示至少一个 source 摄入失败，不能初始化 Official Baseline。
- `materialized` 表示已生成候选对象、关系和指标，但尚未确认。
- `pending_review` 表示等待管理员或质量负责人确认。
- `ready` 表示 Official Baseline 可供版本 fork。
- `stale` 表示 source 有新增变更或版本回写后需要刷新画像。

### 5.5 最低对象与关系

V1 至少生成：

- `ContextObject`：system、module、service、component、page、api、requirement、us、test_case、automation_asset、risk_pattern。
- `ContextRelationship`：contains、implements、depends_on、calls、exposes、verifies、impacts、derived_from、evidenced_by。
- `QualityMetricSnapshot`：code_quality、us_completion_quality、test_quality、release_readiness。

V1 至少支持三条核心关系路径：

- `US -> impacted code objects`
- `AcceptanceCriteria -> TestCase / AutomationScript`
- `AutomationScript -> API / Page / Module`

每个正式对象和关系必须包含 `source_refs`、`confidence`、`freshness_at` 和 `baseline_id`。

### 5.6 基线与版本 overlay

- Official Baseline 是项目长期系统画像的正式事实源。
- Version Working Baseline 必须从 Official Baseline fork。
- 版本期间新增知识只写 overlay，不直接污染 Official Baseline。
- 查询遵循 overlay first、parent fallback。
- 候选知识必须经审批后才能进入 Version Shared 或 Official Baseline。

### 5.7 对外能力

系统画像模块必须支持：

- 查看系统画像摘要、source 状态和摄入进度。
- 按 US、模块、接口、测试资产查询上下文。
- 构建 `TaskContext`。
- 构建 `QualityProfile`。
- 构建 `RegressionProfile`。
- 构建 `CoverageMatrix`。
- 为放行评估提供 release readiness 的上下文和指标。
- 展示对象图谱、证据链、置信度和 freshness。

### 5.8 验收标准

- 无真实三源绑定时，系统只能创建 slots 和追问，不能初始化正式基线。
- 给定真实代码、US 文档和测试资产，系统能生成可审计 RawAsset、ContextObject、ContextRelationship 和 QualityMetricSnapshot。
- 失败 source 不污染 Official Baseline。
- 输入一个 US，系统能返回相关代码对象、历史相似 US、测试资产、覆盖缺口、风险和证据。
- 输入一个新增 US 和 Git delta，系统能返回验证点、测试用例建议、自动化蓝图、回归范围和历史功能保护证据缺口。
- 创建版本后，版本新增知识只写 overlay。
- Official Baseline 初始化必须经过确认或审批，并产生 AuditEvent。

## 6. Agent 主体模块需求

### 6.1 模块目标

Agent 主体模块是 Nasus 的中枢服务，负责把用户目标变成可执行、可审计、可恢复的工作过程。

Agent 不是页面聊天框。它必须具备会话管理、记忆管理、工具规划、目标推进、并行协作、预算控制和治理集成能力。

### 6.2 Agent-first 交互要求

- 主会话是第一操作入口。
- 用户可以用自然语言完成项目、系统画像、版本、US、执行、治理和查询动作。
- UI 按钮、表单、chip 和卡片动作只是同一工具体系的可视化封装。
- 所有写动作必须落成 `ToolInvocation`。
- 普通查询也应优先走查询工具或可审计 read model，而不是前端关键词路由。

### 6.3 Orchestrator 决策

`Conversation Orchestrator` 只能输出四类结果：

- `ClarificationRequest`：上下文不足，需要追问。
- `DirectAnswer`：纯查询或说明，不推进业务状态。
- `ToolInvocationPlan`：明确的单步或多步工具调用计划。
- `AgentGoalProposal`：需要自主规划、暂停/恢复或多步推进的高级目标。

决策要求：

- 高风险动作可以被规划，但不能直接执行绕过 gate。
- 缺少 source、US、版本、权限或审批上下文时必须追问或暂停。
- Agent 不能把写操作伪装成直接回答。

### 6.4 AgentGoal 与 AgentStep

AgentGoal 状态：

`pending -> running -> paused -> completed / failed / cancelled`

AgentStep 阶段：

`thinking -> acting -> observing -> deciding`

需求：

- 每个 AgentGoal 只能在同一 conversation 中保持一个 active controller。
- 每个 AgentStep 必须记录 selected tool、tool invocation、memory summary、decision rationale 和 evidence refs。
- `pause_reason` 至少覆盖 missing_source_binding、waiting_confirmation、waiting_approval、requires_followup、budget_exhausted、user_interrupt。
- paused goal 在刷新、断线或服务重启后必须能恢复。
- 用户补充缺失 source 或确认 gate 时，必须恢复原 AgentGoal，不得新建平行目标。

### 6.5 记忆需求

Agent 记忆分四层：

- Working Memory：当前 AgentGoal 的目标、步骤、工具观察和预算。
- Conversation Memory：最近消息、summary checkpoint、用户反馈和会话工具历史。
- Project Long-term Memory：系统画像、Official Baseline、历史质量资产、执行证据和已批准规则。
- Candidate Memory：候选风险、候选关系、候选验证策略、候选失败归因。

要求：

- 所有 LLM 调用前必须由 Agent Memory Manager 组装上下文。
- 记忆上下文必须带 context hash 和摘要。
- 前端可以查看使用了哪些记忆摘要和证据引用，但不暴露完整 prompt dump。
- 候选记忆不能直接进入长期记忆，必须经过 Merge/Score 和 Approval。

### 6.6 Tool Invocation 与治理

- Agent 只能通过 ToolInvocationRuntime 执行业务动作。
- ToolInvocation 必须经过 context binding、policy check、capability check、confirmation/approval gate、execution、result materialization。
- `initiator_surface=agent_loop` 且 `initiator_actor=agent` 的动作必须同样审计。
- high / critical 工具默认进入 confirmation 或 approval。
- 所有工具结果必须包含 summary、object refs、evidence refs、follow-up 和 recommended next tools。

### 6.7 多 Agent 协作

V1 允许 AgentSwarm 用于：

- 大型系统画像接入后的关系抽取和交叉验证。
- 多 US 并行质量评估。
- 多模块影响分析。
- 多失败批量归因。

约束：

- Swarm 必须绑定 parent AgentGoal。
- 每个 worker assignment 只能产出候选结果。
- 正式结论仍必须进入 Merge/Score 和 Approval。
- Swarm 必须受并发、预算、超时、工具次数和风险 gate 控制。

### 6.8 事件与前端可见性

前端至少要展示：

- AgentGoalCard
- AgentStepRail
- ThinkingCard
- ToolInvocationTimeline
- MemoryContextPanel
- SwarmRunPanel
- Gate Card

事件要求：

- `agent.goal.updated`
- `agent.step.updated`
- `agent.step.thinking.delta`
- `tool.invocation.updated`
- `agent.swarm.updated`

事件必须支持前端 reducer 精确合并，不得只作为全量 refetch 提示。

### 6.9 验收标准

- 用户输入高层目标后，系统能创建 AgentGoal 并自动推进工具链。
- 每个 Agent 动作都能追溯到 AgentGoal、AgentStep、ToolInvocation、ToolResult 和 AuditEvent。
- 高风险动作不会绕过 gate。
- AgentMemoryContext 能解释本次回答使用的短期、会话、长期和候选记忆摘要。
- paused goal 可恢复。
- Swarm 只产出候选结果，不直接写正式结论。
- 循环、预算、rate limit 或 max steps 达阈值时，Agent 必须暂停或升级人工处理。

## 7. 质量闭环主体模块需求

### 7.1 模块目标

质量闭环主体模块负责把一次变更从“理解”推进到“是否准备好上线”的判断。

它是 Nasus 的业务价值主线，必须形成可审计的验证资产、执行证据、失败归因、放行建议和知识沉淀。

### 7.2 版本与 US 需求

版本创建采用分步工具链，但必须最终形成完整版本工作区：

`version.create -> version.inputs.import -> version.branch.bind -> version.participants.assign -> version.risk.initialize`

要求：

- Version 必须从 Official Baseline fork 出 Version Working Baseline。
- US 导入必须支持外部 US ID、标题、描述、验收标准、优先级、负责人和风险提示。
- USWorkItem 与 Task 为 1:N。
- 一个 US 可以并行存在分析、场景、用例、自动化、执行、变更文档等多个 Task。
- 版本级风险视图必须聚合 US 风险、执行状态、审批状态和未闭环项。

### 7.3 TaskContext 需求

TaskContext 是质量闭环的上下文前置条件。

状态：

`building -> ready -> incomplete -> stale`

必须包含：

- US 描述和验收标准。
- 相关 ContextObject 和 relationship。
- 版本 overlay 中的增量知识。
- 相关历史 US、测试资产、失败模式和执行证据。
- 缺失上下文列表和风险提示。

规则：

- TaskContext 未 ready 时，不能进入正式质量资产生成。
- 系统画像变更、版本 overlay 变更或 US 内容变更后，相关 TaskContext 必须 stale。

### 7.4 QualityProfile 需求

QualityProfile 定义某个 Task 的验证策略。

必须包含：

- risk rating。
- verification strategy。
- regression scope。
- automation suitability。
- data and environment requirements。
- performance / security / permission 是否需要覆盖。
- evidence requirement。

规则：

- QualityProfile 可以由 Agent 生成候选，但人工修改必须审计。
- 高风险 US 必须要求更完整的异常、权限、数据和回归覆盖。
- QualityProfile 通过后才能进入执行准备。

### 7.5 QualityAssetPack 需求

QualityAssetPack 是 US 级聚合对象，固定为 `USWorkItem 1:1 current pack`。

资产 part 至少包括：

- scope
- scenario
- plan
- case
- automation
- performance
- change_doc
- summary

每个 part 必须有：

- status
- revision
- source_refs
- evidence_refs
- generated_by
- reviewer
- approval_state

规则：

- 支持局部重生成。
- 支持 part-level review。
- 支持 pack-level revision。
- 并发修改冲突进入 pending_merge。
- AssetPack 不能只存 markdown 文本，必须有结构化字段和可追溯引用。

### 7.6 执行与证据需求

Run 是唯一正式执行对象。

Run 状态：

`pending -> running -> succeeded / failed / retrying / pending_merge / closed`

ExecutionEvidence 必须 append-only，并至少覆盖：

- log
- screenshot
- trace
- video
- report
- assertion_result
- environment_snapshot
- failure_artifact

要求：

- 每个 evidence 必须有 storage ref、hash、producer、captured_at 和关联 run/case。
- 执行证据要能在 Run Detail、Approval Detail 和 Release Readiness 中复用。
- evidence 需要支持脱敏、保留策略和回放入口。

### 7.7 失败归因与自愈需求

FailureReport 必须包含：

- failure_kind
- failure_fingerprint
- summary
- suspected_causes
- confidence
- evidence_refs
- owner_hint
- next_actions

failure_kind 至少包括：

- product_bug
- test_script_issue
- environment_issue
- test_data_issue
- flaky
- requirement_ambiguity
- unknown

自愈规则：

- HealingProposal 只能作为建议，不能直接写入正式结论。
- 相同 failure fingerprint 必须受 cooldown 控制。
- 自动自愈必须受 max healing depth 限制。
- 达到阈值后必须 fallback-to-human。

### 7.8 放行建议与治理需求

Release Readiness 状态：

`ready -> conditional -> blocked -> needs_evidence`

放行建议必须基于：

- US 闭环状态。
- QualityAssetPack 审核状态。
- Run 成功率和失败状态。
- Evidence 充分性。
- Approval 状态。
- 未解决 pending_merge。
- 候选知识是否需要晋级。

规则：

- Agent 可以生成放行建议，但不能直接写正式放行结论。
- 正式结论必须经过 `AgentDecision -> MergedResolution -> ApprovalRecord`。
- `baseline.promote` 只能在版本收口或上线审批通过后执行。
- 基线回写必须保留来源、差异、证据、审批和审计事件。

### 7.9 验收标准

- 一个版本可以从正式基线创建工作基线，导入 US，完成 owner 分配和初始风险视图。
- 单个 US 必须先生成 TaskContext 和 QualityProfile，再进入质量资产生成。
- QualityAssetPack 支持结构化 part、局部重生成、review、revision 和 pending_merge。
- 每次正式执行生成 Run 和 append-only Evidence。
- 执行失败生成结构化 FailureReport。
- Release Readiness 基于所有 US、资产、执行、失败、审批和未闭环项聚合。
- 正式放行、知识晋级和基线回写必须可追溯、可审批、可审计。

## 8. 跨模块需求

### 8.1 工具原生

所有核心业务动作必须注册为 ToolDefinition，并通过 ToolInvocation 执行。模块间不得通过隐藏的 UI-only 或 service-only 写路径推进状态。

### 8.2 状态可恢复

以下对象必须支持刷新和服务重启后恢复：

- ConversationSession
- AgentGoal
- ToolInvocation
- ConnectorRun
- Baseline
- Task
- Run
- ApprovalRecord

### 8.3 审计与追踪

每个业务动作必须至少能追溯：

- actor
- conversation_id
- agent_goal_id
- tool_invocation_id
- domain object refs
- evidence refs
- approval refs
- timestamp
- result summary

### 8.4 前端体验

前端必须保持 agent-first：

- Build 用主 composer 引导项目创建和 source 接入。
- Dashboard 用主 composer 查询全局风险和进展。
- Project Space 展示系统画像、source、baseline、版本和 Agent 会话。
- Version Space 展示 US board、版本风险、执行和审批。
- Personal Workspace 展示 Agent 过程、QualityAssetPack、ToolInvocationTimeline 和 Run settings。
- Runs 和 Governance 必须能回溯证据链和审批链。

## 9. V1 验收总标准

- 在一个真实或真实结构的 Web 项目上完成三源接入。
- 系统画像能生成可追溯对象、关系和指标。
- 主会话能驱动系统画像初始化、版本创建、US 质量闭环和进度查询。
- 单个 US 能完成 TaskContext、QualityProfile、QualityAssetPack、Run、Evidence、FailureReport 和 Release Readiness。
- Release Readiness 必须能形成正式 `ReleaseDecision`，并说明 ready / conditional / needs_evidence / blocked 的依据。
- 高风险动作必须进入 confirmation 或 approval。
- 刷新页面后关键状态不丢失。
- 所有正式结论和基线回写都有审批与审计链路。
- 认证、授权、密钥保护、PostgreSQL / Alembic、SSE replay、审计、备份、CI 和可观测性必须作为生产 release gate。

## 10. 需求优先级

| 优先级 | 需求 |
| --- | --- |
| P0 | 三源接入、系统画像 ready、PostgreSQL FTS + pgvector hybrid retrieval、embedding / rerank adapter、AgentGoal 工具链、ToolInvocation、TaskContext、QualityProfile、QualityAssetPack、Run、Evidence、FailureReport、Release Readiness、ReleaseDecision、approval、pending_merge、baseline.promote、生产非功能 gate |
| P1 | Agent Step streaming 增强、MemoryContextPanel 深化、Swarm V1 扩展、局部重生成增强、复杂失败归因、多策略评分 |
| P2 | UX / OpenAPI / 缺陷 / 执行日志增强 source、独立 Weaviate / OpenSearch / Qdrant 检索投影、高级召回评测和知识晋级自动建议 |
| P3 | Desktop / Edge、本地高权限工具、公网 SaaS 多租户、大规模外部集成 |
