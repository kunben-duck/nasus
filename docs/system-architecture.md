# 整体架构与部署设计

## 0 文档优先级说明

- 本文用于说明 Nasus 的系统分层、部署单元和实现约束。
- 当前需求对应的生产准入、P0 纵切、开发顺序和技术契约冻结要求，以 [技术方案设计基线](./technical-solution-baseline.md) 为准。
- 若本文与 [最终特性说明书](./final-feature-spec.md) 存在冲突，以最终特性说明书定义的产品能力和默认规则为准。
- 尤其在 Agent 能力边界上，本文保留当前实现语义中的分层约束；最终产品能力以“Agent 可原生触发检索与执行，但必须受策略、审计和回放约束”为准。

## 1 设计目标与边界
- 目标：构建一个**质量保障与上线防护平台**，当前阶段采用“中心 Web 控制面 + 确定性 Web 执行”的架构，用统一上下文加治理机制替代传统的测试生成器，确保每次变更都能被理解、验证、执行、归因并给出放行建议。[计划书](./nasus_assurance_studio_implementation_plan.md#L14)
- 交互前提：平台采用 `agent-first` 形态，主会话是第一操作入口，所有业务动作原生都必须支持主 Agent 调用；页面按钮、表单和卡片动作只是同一工具体系的可视化封装。
- 技术边界：核心能力是上下文建模、领域服务编排与治理，执行层（Playwright）和原料（Git/docs/UX）通过防腐层隔离接入，避免将执行细节耦合在决策路径。[计划书](./nasus_assurance_studio_implementation_plan.md#L346)
- 质量原则：统一上下文、物化系统画像、版本期间只更新工作基线、会话知识默认私有，追求可解释、可追溯、可审计。[计划书](./nasus_assurance_studio_implementation_plan.md#L57)
- 形态原则：当前阶段以 Web 端作为唯一正式工作入口和执行编排面。

## 1.1 三大产品模块在整体架构中的位置

Nasus 的产品一级模块固定为 3 个：

1. **系统画像构建模块**
2. **Agent 主体模块**
3. **质量闭环主体模块**

它们不是三个彼此独立的子系统，而是同一条主线上的三个层次：

`系统画像构建 -> Agent 主体 -> 质量闭环主体`

也就是：

- **系统画像构建模块** 提供统一上下文，是整个系统的“眼睛”。
- **Agent 主体模块** 是贯穿全系统的 `Agent Service`，负责理解目标、管理记忆、规划步骤、调用工具、调度并行 Agent 并收敛结果，是系统的“主驱动层”。
- **质量闭环主体模块** 负责把一次变更推进到可审计的验收结果和上线判断，是产品的“业务价值主线”。

从架构角度看，三者的关系需要同时满足两条原则：

- **产品交互原则：Agent-first**
  用户默认通过主会话与 Agent 发起工作。
- **系统实现原则：Domain-first, Tool-native**
  系统画像和质量闭环必须先是正式领域能力，再由 Agent 统一驱动，不能把核心业务逻辑埋进会话或 prompt。

## 1.2 模块依赖关系

| 产品模块 | 回答的问题 | 上游依赖 | 下游输出 |
| --- | --- | --- | --- |
| 系统画像构建模块 | 当前系统是什么、这次变更影响了什么 | 原料接入、索引与解析、基线治理 | `ContextObject`、`Baseline`、`TaskContext`、`QualityProfile` |
| Agent 主体模块 | 用户当前要完成什么、下一步该做什么 | 系统画像、工具目录、策略与权限 | `ToolInvocationPlan`、`AgentGoal`、会话级决策与推进 |
| 质量闭环主体模块 | 这次变更是否真的准备好上线 | 系统画像上下文、Agent 驱动、执行与治理能力 | 质量资产、执行证据、放行建议、知识沉淀 |

依赖约束必须写死：

- 质量闭环不能跳过系统画像直接工作，否则会退化成脱离上下文的测试生成器。
- Agent 不能绕过工具和治理直接操作正式领域对象，否则会退化成不可审计的聊天系统。
- 系统画像不能脱离质量闭环自我膨胀，否则会退化成“大而全知识图谱工程”。
- Agent Service 不能只保留短期 prompt 历史，必须显式管理短期工作记忆、会话记忆、长期系统画像记忆和候选知识。
- 多 Agent 并行只能提升分析和生成效率，不能越过 `Merge/Score`、审批和正式事实边界。

## 2 核心对象模型
- Raw Assets（原料层）保存 Git、文档、UX、OpenAPI、历史验证资产、缺陷等输入，强调 append-only 和证据化。[计划书](./nasus_assurance_studio_implementation_plan.md#L69)
- Context Objects 是可推理的系统画像（System/Module/Feature/Page/API/CodeSymbol/Requirement/UXArtifact/TestAsset/RiskPattern/ExternalDependency/Role/State），带关系（contains/implements/depends_on/impacts 等）与证据。[计划书](./nasus_assurance_studio_implementation_plan.md#L83)
- Workspaces（版本工作基线、Task Context Workspace、Quality Assurance Profile、Session Context、Candidate Knowledge）将版本、任务与会话捆绑，为每次变更构建“动态上下文”。[计划书](./nasus_assurance_studio_implementation_plan.md#L111)
- 治理对象分四层：Project/Version/Session/Baseline，知识分级为 Official/Version Shared/Session-only/Candidate，确保变更期间只更新工作基线，版本完成后经审批回写官方基线。[计划书](./nasus_assurance_studio_implementation_plan.md#L189)
- 工具对象补充为 `Conversation Session`、`ToolDefinition`、`ToolInvocation`、`ToolResult`，用于承载主会话输入、统一动作目录、命令执行记录和结构化结果。
- Agent Service 对象补充为 `AgentGoal`、`AgentStep`、`AgentMemoryItem`、`AgentSwarmRun`、`AgentWorkerAssignment`，用于承载自主目标、步骤、记忆引用和多 Agent 并行任务。

## 3 七层系统架构
1. Experience Layer：Web Portal、CLI、API、Nasus Assistant 作为人机入口。[计划书](./nasus_assurance_studio_implementation_plan.md#L346)
2. Intelligence Orchestration Layer：`Conversation Orchestrator`、`Agent Service`、`Agent Supervisor`、`Agent Memory Manager`、`Agent Swarm Coordinator`、Tool Registry、Tool Invocation Runtime、Skill Registry、Workflow、Worker Scheduler、Merge/Score Engine、Approval Control 负责理解会话、管理记忆、选择工具、路由能力、并发和审批。[计划书](./nasus_assurance_studio_implementation_plan.md#L348)
3. Domain Intelligence Layer：Baseline/Impact/Verification Planning/Scenario/Case/Automation/Failure/Healing/Release Advice 等领域服务产出决策。[计划书](./nasus_assurance_studio_implementation_plan.md#L370)
4. Unified Context Engine：Source Connectors、Code/Knowledge Intelligence、Anchor Extraction、Entity Resolution、Context Assembler、Context Object Store，统一加工上下文对象并对上只暴露 `get_feature_context`、`build_task_context`、`build_quality_profile`、`assess_release_readiness`。[计划书](./nasus_assurance_studio_implementation_plan.md#L267)
5. Three-Layer Context System：Historical System Baseline、Task Context Workspace、Quality Assurance Profile 支撑任务理解与质量画像。[计划书](./nasus_assurance_studio_implementation_plan.md#L123)
6. Integration Fabric（防腐层）：Asset Ingestion、Execution、Storage、Review/Policy、Provider Contracts、Adapter Registry，隔离具体 Git、文档系统和执行器差异。[计划书](./nasus_assurance_studio_implementation_plan.md#L393)
7. Infrastructure Providers：Git、Docs、OpenAPI、Tree-sitter、Codebase Memory（可替换图投影）、Object Store、PostgreSQL、Playwright、Queue、Scheduler 等外部能力。

### 3.1 七层架构与三大产品模块的映射

| 架构层 | 对应产品模块 | 说明 |
| --- | --- | --- |
| Experience Layer | Agent 主体模块、质量闭环主体模块 | 用户在 `Build / Dashboard / Project / Version / Personal Workspace` 中通过主会话驱动工作 |
| Intelligence Orchestration Layer | Agent 主体模块 | 承载 `Conversation Orchestrator`、`Agent Service`、`Agent Memory Manager`、`Agent Loop`、`Agent Swarm`、`ToolInvocation`、Goal 推进 |
| Domain Intelligence Layer | 质量闭环主体模块 | 承载影响分析、验证规划、场景生成、执行归因、放行建议等主业务能力 |
| Unified Context Engine | 系统画像构建模块 | 承载接入、解析、实体抽取、上下文组装 |
| Three-Layer Context System | 系统画像构建模块、质量闭环主体模块 | 把长期系统知识转成版本级与任务级上下文 |
| Integration Fabric | 三个模块共享 | 为系统画像、Agent、质量闭环提供统一接入与执行防腐层 |
| Infrastructure Providers | 三个模块共享 | 存储、索引、执行、调度等底座 |

## 4 逻辑架构与运行平面

- **控制面（Control Plane）**：Web Portal + API Gateway + Policy/Approval Service，负责角色验证、资源授权、任务划分、组织治理和统一监控，构成 `settings` + `approval` 中央治理层。
- **工具契约面（Tool Contract Layer）**：`Conversation Orchestrator` + `Tool Registry` + `Tool Invocation Service` + `Confirmation / Approval Gate`，负责把会话输入、页面动作和外部 API 请求统一映射成可治理的工具调用。
- **智能面（Intelligence Plane）**：Unified Context Engine + Domain Intelligence Services + `Agent Service` + `Agent Memory Manager` + `Agent Swarm Coordinator` + `Skill Registry` + `Merge/Score`，负责构建 `Task Context` + `Quality Profile`，并为工具执行提供可直接消费的编排能力。
- **执行面（Execution Plane）**：Web Execution Fabric + Runner + Failure/Healing + Execution Evidence Store，负责网页端工具、Playwright/MCP 调用、确定性执行、失败归因和 patch 建议。
- **数据面（Data Plane）**：PostgreSQL + pgvector + MinIO + Tree-sitter + Codebase Memory projection + Audit/Event Store，提供事实源、证据归档、结构解析、可替换代码图谱、语义检索和检索运行审计。OpenGrok 可作为后续全文导航投影接入，不是 V1 canonical 依赖。

运行平面说明：

- `Control Plane` 为最终特性说明书定义的“Agent 可触发”能力提供治理和策略入口。
- `Tool Contract Layer` 是所有写操作的 canonical command surface。无论动作来自主会话、按钮、表单还是批量操作，本质上都必须先形成 `ToolInvocation`。
- `Intelligence Plane` 内部分为三层：`Agent Service` 负责目标、记忆、蜂群和结果收敛；`Durable Workflow Runtime` 负责长生命周期任务、审批等待、重试和恢复；`Agent Graph Runtime` 负责单个目标 iteration 或单个工具内部的 Skill 路由、人机节点和局部并行。
- `Execution Plane` 负责承接 Web 触发的网页端工具、Playwright 和 MCP 请求。
- `Data Plane` 对所有行为提供事实源、审计与证据保留。

所有平面最终共享统一任务模型、统一 `Run` 模型和统一 `evidence` 模型。

### 4.1 三大产品模块在运行平面中的落位

| 产品模块 | 主要运行平面 | 核心组件 | 关键输出 |
| --- | --- | --- | --- |
| 系统画像构建模块 | `Intelligence Plane` `Data Plane` `Integration Fabric` | `Unified Context Engine`、`Source Connectors`、`Context Object Store`、`Baseline Service` | `System Image`、`Baseline`、`TaskContext`、`QualityProfile` |
| Agent 主体模块 | `Control Plane` `Tool Contract Layer` `Intelligence Plane` | `Conversation Orchestrator`、`Agent Service`、`Agent Memory Manager`、`Agent Swarm Coordinator`、`Tool Registry`、`Tool Invocation Service`、`Agent Graph Runtime`、`LLM Runtime` | `Conversation Session`、`ToolInvocationPlan`、`AgentGoal`、`AgentSwarmRun` |
| 质量闭环主体模块 | `Intelligence Plane` `Execution Plane` `Control Plane` | `Verification Planning`、`Scenario/Case`、`Automation Service`、`Failure/Healing`、`Approval Control`、`Release Advice` | `QualityAssetPack`、`Run`、`Evidence`、`MergedResolution` |

这三者的运行关系必须保持稳定：

1. 系统画像构建先产出可被消费的上下文对象和基线。
2. Agent 主体只通过工具目录和正式领域能力消费这些上下文。
3. 质量闭环主体把 Agent 的规划落成正式对象、执行证据和放行判断。

## 5 核心组件职责矩阵

### 5.0 代码分层落地约束

整体架构在代码中按 DDD 渐进式落地，详细规范见
[后端代码架构与 DDD 分层](./design/backend/code-architecture.md)。

当前后端代码必须遵守以下约束：

- `interface/http` 只负责协议转换和错误映射，不允许直接 import 全局 `store`。
- `application/<domain>` 是 router 和 workflow activity 调用的唯一业务入口；HTTP 与 Temporal 入口统一从 `bootstrap/ApplicationContainer` 获取应用服务，禁止 import 全局 `store`。迁移期兼容投影只能被 bootstrap 内部组装，不能泄漏到入口层或承载新增业务规则。
- 系统画像读模型入口必须通过 `application/system_image`，不继续塞进项目 BFF。
- `domain/<domain>` 只保存纯领域规则，不依赖 FastAPI、ORM、LLM、对象存储或工作流引擎。
- `infrastructure/*` 承接 PostgreSQL、MinIO、LLM、Temporal/LangGraph 和 Runner 适配。
- 所有正式写动作仍以 `ToolInvocationRuntime` 为审计主线。

| 组件 | 主要职责 | 依赖 |
| --- | --- | --- |
| Conversation Orchestrator | 接收主会话输入，理解意图，补足上下文，产出 `ToolInvocationPlan` | Tool Registry、Unified Context Engine、Policy Service |
| Agent Service / Supervisor | 管理 `AgentGoal` 生命周期、自主级别、预算、目标拆分和执行策略 | Conversation Orchestrator、Agent Memory Manager、Tool Registry、Policy Service |
| Agent Memory Manager | 组装 LLM 上下文窗口，维护工作记忆、会话记忆、长期系统画像记忆和候选知识 | Conversation Store、Unified Context Engine、Baseline Service、Audit Store |
| Agent Swarm Coordinator | 将复杂目标拆分为多个并行子 Agent 任务，控制并发、预算和超时 | Agent Service、Worker Runtime、Merge/Score、Policy Service |
| Tool Registry | 管理 `ToolDefinition`、工具分类、风险等级、确认方式和输入输出 schema | Policy Service、Skill Registry、Domain Services |
| Tool Invocation Service | 统一执行 `ToolInvocation`，完成 context binding、policy check、gate 控制和结果物化 | Tool Registry、Durable Workflow Runtime、Approval Control |
| Confirmation / Approval Gate | 承接高风险工具动作的用户确认、审批等待和策略放行 | Tool Invocation Service、Policy Service、Approval Control |
| Central Orchestrator Agent | 在 Agent Service 内负责中心侧 planning、工具选择和候选结论生成 | Skill Registry、Durable Workflow Runtime、Agent Graph Runtime、Approval Control |
| Durable Workflow Runtime | 承接长生命周期任务、审批等待、超时、重试、恢复编排 | API/Orchestrator、Queue、Approval Control |
| Agent Graph Runtime | 在单个 AgentGoal iteration 或单个工具内部执行阶段规划、Skill 路由、并行 Worker 编排和人机节点控制 | Skill Registry、Worker Runtime、Merge/Score |
| Skill Registry | 管理 `SkillDefinition`、标记 `scope=central`，作为工具背后的能力目录 | Policy Service、Worker Runtime、Context Assembler |
| Worker Runtime | 调度 Context/Impact/Scenario/Failure 等 Worker，收集 partial result 并提交 Merge/Score | Context Assembler、Domain Services、Execution Fabric |
| Unified Context Engine | 统一感知 Raw Assets、上下文对象、Evidence，提供 `get_feature_context`、`build_task_context`、`build_quality_profile` | Source Connectors、Code/Knowledge Intelligence、Entity Resolution、Context Object Store |
| Merge/Score + Conflict Resolver | 合并中心端 `AgentDecision`、识别冲突、输出 `MergedResolution` 建议 | Agent Graph Runtime、Approval Control、Execution Evidence |
| Approval Control & Release Advice | 评估证据、驱动 Candidate 晋级、提供放行建议、记录审批链、确认正式结论 | Quality Profile、Execution Evidence、Policy Service、Merge/Score |
| Automation Service & Runner | 转换验证方案->Playwright 资产、调度 Runner、采集 Logs/Screenshots，承接 Web 端 Playwright/MCP 执行 | Workflow Runtime、Queue/Scheduler、Failure Analysis |

## 6 关键对象、状态与事件流

| 对象 | 典型状态 | 触发事件 | 下游影响 |
| --- | --- | --- | --- |
| `Project` | 未接入 -> 接入中 -> 待审核 -> 已建档 | Provider 接入、材料完成、管理员确认 | 启动版本建模、提供 Governance |
| `Version` | 草稿 -> 进行中 -> 待收口 -> 已收口 | Fork Official Baseline、提交 Review、审批通过 | 推动 Session、触发 Change Set |
| `Session` | 未开始 -> 进行中 -> 暂停 -> 结束 | 用户创建、任务提交、执行完成 | 驱动 Task Context、Execution Runner |
| `Conversation Session` | 新建 -> 活跃 -> 暂停 -> 完成 | 用户发言、Agent 响应、工具执行完成 | 形成 `ToolInvocation` 与对象引用主链路 |
| `ToolInvocation` | pending -> running -> waiting_confirmation / waiting_approval -> completed / failed / cancelled | 会话输入、页面动作、外部 API 请求 | 驱动 workflow、写入对象、产生审计事件 |
| `AgentGoal` | pending -> running -> paused -> completed / failed / cancelled | 主会话高级目标、用户打断、Gate、预算耗尽 | 驱动 Agent Loop、工具调用和 Swarm |
| `AgentSwarmRun` | pending -> running -> merging -> completed / partially_failed / failed / cancelled | 复杂目标拆分、多 US 分析、多模块归因 | 产出多个候选结果并进入 Merge/Score；部分失败时保留缺失证据 |
| `Task Context Workspace` | 构建中 -> 完成 -> 失效 | Agent/Tool 执行、证据补全 | 供 `Quality Profile`、自动化执行使用 |
| `Quality Assurance Profile` | Draft -> Reviewed -> Approved | Verification/Scenario/Case 完成、人工确认 | 触发 automation.run 与 release.assess |
| `AgentDecision` | provisional -> merged -> approved / rejected | 中心端推理完成、Conflict Resolver、Approval Control | 推动正式任务结论、正式放行或知识晋级 |
| `MergedResolution` | pending_merge -> ready_for_approval -> approved / rejected | Merge/Score 完成、Approval Control 决策 | 写入正式任务状态、Release Advice、Knowledge Resolution |
| `Candidate Knowledge` | 待审批 -> 版本共享 -> 官方 | Approval Control 决策 | 修改 Version Shared / Official Baseline |
| `Run` | 待执行 -> 执行中 -> 成功/失败/重试/pending_merge | Automation Service 触发 | 归因、Approval、Release Advice |
| `Task` | draft -> analyzing -> pending_merge -> ready_for_review -> executing -> ready_for_release -> completed | Tool invoke、AgentDecision 提交、Run 完成、Merge/Approval 完成 | 影响任务 UI、审批流和知识晋级 |

| 事件流 | 描述 |
| --- | --- |
| 工具调用事件 | Conversation/UI/API 请求 -> `ToolInvocation` 创建 -> Policy/Gate -> Domain Object/Workflow |
| 项目接入事件 | Provider/Material ingestion -> Raw Assets indexed -> Historical System Baseline snapshot |
| 版本 fork 事件 | `Official Baseline` 被 `Version Working Baseline` fork，`Change Set` 生成并入队 Agent |
| 会话入队事件 | 用户选版本、创建 Session，向 Agent 提供材料 -> Agent 解析为 `ToolInvocationPlan` -> `Task Context` 触发工具执行 |
| Agent 记忆事件 | 会话、工具结果和系统画像对象被摘要 -> Agent Memory Manager 更新工作记忆、会话记忆或候选记忆 |
| Agent 蜂群事件 | AgentGoal 拆分多个 AgentWorkerAssignment -> 并行工具调用 -> Agent Result Merger -> Merge/Score |
| 执行证据事件 | Runner 完成 `Run` 后推送 Logs/Screenshots -> Failure/Healing/Event Store append |
| 冲突合并事件 | 中心端产生冲突的 `AgentDecision` 或结构化候选结果 -> Task/Run/Knowledge 进入 `pending_merge` -> Merge/Score 生成 `MergedResolution` |
| 知识晋级事件 | Approval Control 判断 -> Candidate 升级 -> Baseline Service 写回 |

## 7 核心数据流
1. 项目接入：管理员导入原料（Git/文档/US/设计/UX/OpenAPI/历史验证资产），系统完成索引、结构候选抽取、特性关系关联，输出 Historical System Baseline；管理员审核后形成 Official Baseline v1。[计划书](./nasus_assurance_studio_implementation_plan.md#L528)
2. 版本创建：管理员/授权角色导入版本 US/文档/UX/OpenAPI/提交范围，系统从 Official Baseline fork 出 Version Working Baseline，建立 Change Set，并做初步风险识别。[计划书](./nasus_assurance_studio_implementation_plan.md#L547)
3. 会话与协作：授权用户在 Web 中开 Session，上传材料。系统先把用户输入解析成 `ToolInvocationPlan`，再由工具调用推进 Task、Run 和审批链。系统用 Feature Graph/Change Graph 提示相关会话、识别重复和共享风险，并允许合并验证任务。Session-only 知识默认不进基线，可申请晋升为 Candidate。[计划书](./nasus_assurance_studio_implementation_plan.md#L558)
4. Task Context 构成：`历史系统画像 + 当前任务输入 + Web 实时证据`。[计划书](./nasus_assurance_studio_implementation_plan.md#L170)
5. Quality Assurance Profile 构成：`当前任务上下文 + 质量策略规则 + 历史验证资产 + 风险模型 + 审核反馈`，推动影响分析、验证计划、场景、用例、自动化建议。[计划书](./nasus_assurance_studio_implementation_plan.md#L177)
6. 执行与归因：Web 端通过 Playwright/MCP 执行网页操作，生成统一 `Run(execution_channel=web_runner)` 和 evidence，Failure Analysis 识别失败类型，Healing 生成 patch，Release Advice 输出上线准备度建议。[计划书](./nasus_assurance_studio_implementation_plan.md#L444)
7. 冲突与合并：中心端可提交 `AgentDecision`；若候选结论或结构化结果冲突，则任务、放行或知识对象进入 `pending_merge`，由 `Merge/Score + Approval Control` 生成正式 `MergedResolution`。
8. 治理闭环：高价值 `Candidate Knowledge` 先经审批进入 `Version Shared Knowledge`，版本完成后再将经过确认的版本知识回写 `Official Baseline`。[计划书](./nasus_assurance_studio_implementation_plan.md#L615)

## 8 Agent / Tool / Skill / Worker 协作
- 本节描述当前推荐的系统实现约束，不等同于最终产品能力承诺。若与最终特性说明书冲突，以最终特性说明书为准。
- 架构模式：`Agent Service + Agent Supervisor + Agent Memory Manager + Agent Swarm + Tools + Skills + Parallel Workers + Deterministic Core`。Agent Service 负责全局目标规划、上下文记忆、工具选择、并行子 Agent 调度和正式治理流编排。
- 运行时采用“`外层耐久工作流 + 内层图编排`”：
  - `Agent Service` 负责目标、记忆、预算、并发和 swarm 编排。
  - `Durable Workflow Runtime` 负责长任务、审批等待、超时、重试和恢复。
  - `Agent Graph Runtime` 负责阶段推进、工具内部的 Skill 路由、局部并行和人机节点。
- 记忆系统采用四层：
  - `Working Memory`：单个 `AgentGoal` 内的当前步骤、工具结果和预算。
  - `Conversation Memory`：消息、摘要 checkpoint、用户反馈和会话级工具结果。
  - `Project Long-term Memory`：系统画像、正式基线、历史质量资产和执行证据。
  - `Candidate Memory`：尚未审批的候选风险、候选关系、候选策略和候选归因。
- Tool 是产品级动作抽象，统一由 `Tool Registry` 管理，并标记：
  - `tool_kind=project|version|us|analysis|execution|governance|query`
  - `scope=central`
  - `risk_level=low|medium|high|critical`
  - `confirmation_mode=none|user_confirm|approval_required|policy_only`
- Skill 是工具背后的内部能力组件，统一由 `Skill Registry` 管理，并标记：
- `scope=central`：如 `baseline.build`、`impact.analyze.global`、`verification.plan`、`failure.analyze`、`healing.propose`、`context.enrich`、`evidence.summarize`、`release.assess`。
- 所有业务动作默认都要先经过工具层。页面按钮、批量操作和主会话输入都应先变成 `ToolInvocation`，再由工具内部去编排 Skill 和 Worker。
- Workers 仍按 Context（frontend/backend/document/API/historical assets）、Impact（diff/requirement/dependency）、Scenario（mainflow/exception/permission/boundary/integration）、Failure（locator/timing/assertion/env）分池，并行产出局部结果交给 `Merge/Score` 收敛。[计划书](./nasus_assurance_studio_implementation_plan.md#L498)
- 复杂目标允许进入 `AgentSwarmRun`：`Agent Supervisor` 把目标拆为多个 `AgentWorkerAssignment`，并行调度专门 worker agent；每个子 Agent 仍必须通过 `ToolInvocation` 执行动作。
- 中心端产生 `AgentDecision(status=provisional)`；冲突时统一进入 `pending_merge`，由 `Merge/Score + Approval Control` 产出正式 `MergedResolution`。
- 协作链路：`Conversation` 解析意图 -> `Agent Service` 绑定记忆与目标 -> `ToolInvocation / AgentGoal` 创建 -> `Workflow` 定阶段 -> `Agent Graph Runtime` 路由 Skill -> `Worker Runtime / Agent Swarm` 并行任务 -> `Merge/Score` 合并候选结果 -> `Approval Control` 决定是否晋升知识、放行或进入下一阶段，保证执行层确定性与结果可审计。[计划书](./nasus_assurance_studio_implementation_plan.md#L474)

## 9 部署架构与运行单元
### 9.1 计划书明确的部署线索
- Experience Layer 对应 `portal`，Domain/Orchestration Layer 集中在 `api/orchestrator` 服务，Integration Fabric 封装 Asset/Execution/Storage 接入，Infrastructure Providers 提供 Git/Docs/PostgreSQL/MinIO/Tree-sitter/Codebase Memory/Playwright/Temporal。
- Storage/Index 基线为 PostgreSQL + pgvector、MinIO、Tree-sitter 和可替换代码图谱；Execution 为 Node.js + Playwright。

### 9.2 基于计划书的最小推断
- 部署模型：`portal`、`api/orchestrator`、`workflow-service`、`runner` 四类中心运行单元；PostgreSQL + pgvector、MinIO 和 Temporal 为外部服务。代码 canonical parse 由 Tree-sitter 完成，Codebase Memory 以 API 镜像内固定版本 CLI 形成可持久化图投影。
- 任务流：Web 发起任务 -> API/Agent 组装统一 Task Context -> `workflow-service` 启动耐久任务 -> `worker-runtime` 生成质量方案和自动化属性 -> Web 触发 Playwright/MCP -> 中心端提交 `AgentDecision` -> 统一 `Run` 和证据回写 PostgreSQL/MinIO -> 冲突时进入 `pending_merge` -> `Approval Control` 决定基线走向。
- 运行环境建议：中心端先以 Docker 模式部署 4 到 5 个运行单元，再按需求扩展到多 worker 池。V1 必须在 PostgreSQL FTS + pgvector 上落地 hybrid retrieval、embedding 和 rerank adapter；若中心检索规模或召回质量逼近瓶颈，再把检索投影迁移到 Weaviate / OpenSearch / Qdrant / Milvus 等独立服务。

## 10 首轮建设到后续演进

- 建议先跑通 Phase0-3（对象协议、项目/版本初始化、任务上下文、质量方案生成），Phase4 补自动化执行与失败分析，Phase5 加审批与基线回写。[计划书](./nasus_assurance_studio_implementation_plan.md#L764)
- 随着成熟度提升，可把 worker 按 Context/Impact/Scenario/Failure 进一步分池、把代码图谱索引从在线请求路径剥离为异步任务，并把 PostgreSQL FTS + pgvector 检索投影平滑替换为专用检索层。

## 11 可靠性、审计、权限与可观测性

- **权限管控**：所有 Project/Version/Session/Knowledge/Approval 操作须通过 RBAC，且必须在 `Settings` 模块明确配置。
- **审计事件**：Control Plane、Tool Contract Layer、Intelligence Plane、Execution Plane 的关键事件（会话发言、工具调用、能力调度、执行、上下文晋级、审批）必须写入不可修改的 Audit Store。
- **证据保留**：所有 `Run` 的日志、截图、trace、Failure 归因、patch 建议、审批决定永远 append-only，并关联 `Task Context`/`Version`。
- **Tool 可调用性与执行权**：所有业务动作都应可被主 Agent 通过工具发起，但是否能够执行必须同时满足 `RBAC + policy`。高风险工具默认进入确认或审批闸口。
- **交互通道**：Portal 到 `api/orchestrator` 的写操作通过 `Conversation` 和 `ToolInvocation` 的 REST 入口完成；任务、执行、审批的长时状态回传采用 SSE；Runner/Worker 与 Orchestrator 之间走队列和内部事件，不直接暴露给前端。
- **执行隔离**：Runner 是独立的 Node.js + Playwright 内部 HTTP 服务，只接受带服务身份的结构化步骤；禁止任意 JavaScript，目标受 host allowlist 约束。Runner 运行在只读、无特权、有限进程和有限并发的隔离容器中，原始截图、trace、日志由 API 写入 MinIO/S3 后才形成正式 Evidence。
- **正式事实来源**：中心端推理只能提交 `provisional` 候选结果；正式事实必须由 `Merge/Score + Approval Control` 写入。
- **命令入口统一**：主会话、页面动作和外部 API 的写操作都应统一形成 `ToolInvocation`；对象查询接口作为 read model 存在，但不再是主业务动作入口。
- **可观测性**：为 Control/Intelligence/Execution 平面提供统一链路追踪、运行指标、队列延迟和失败率；任何 Worker 重启必须能恢复任务状态。
- **数据恢复**：PostgreSQL 级数据采用定期备份，Execution Evidence 通过 MinIO 版本控制；在 worker 异常时，Workflow Runtime 必须可重入。
- **策略与备份**：Promotion Gate、Release Advice Gate、Baseline 回写 Gate 的状态必须持久化，并且有明确回滚/override 流程。

## 12 环境分层与部署建议

| 环境 | 目标 | 默认组成 | 要求 |
| --- | --- | --- | --- |
| `local` | 单开发者调试与联调 | 宿主机直启 `portal` `api/orchestrator` `worker-runtime` `runner`；Docker 提供 `PostgreSQL` `MinIO` | 支持断点调试、最小数据集、假 Provider、低成本重置 |
| `dev` | 多人共享开发环境 | 应用直启或同构部署 + 容器化外部组件 + 持久化代码图谱/文档索引 | 支持真实任务流、事件追踪、最小审批流 |
| `staging` | 预发布验证 | 完整中心平面 + 审计/策略/执行网关 | 接近生产配置，验证权限、审批、回放、恢复 |
| `prod` | 企业正式运行 | 私有化部署、隔离执行环境、备份与监控全量开启 | 强制审计、强制审批、证据长期保留 |

部署建议：

- `local/dev` 调试默认直接启动 API、Portal、workflow worker 和 Runner；Docker Compose 只承载 PostgreSQL、MinIO、Temporal、索引/检索等外部组件。候选发布、staging 和 production 必须使用容器化应用运行单元。
- V1 本地与迁移部署的外部组件基线为 `PostgreSQL + pgvector`、`MinIO/S3`。仓库根目录 `docker-compose.yml` 是 local/dev 的权威入口；staging/prod 可以替换为企业托管 Postgres/S3 或 k8s chart，但服务协议、环境变量和 migration 流程必须保持一致。
- `staging/prod` 推荐迁移到 k8s 或企业内部等价编排平台，并将 `worker-runtime`、`runner`、索引服务拆成独立扩缩容单元。
- `prod` 环境中 `runner` 必须使用隔离网络、独立 service token、host allowlist 与短期任务凭证，不得与控制面共享高权限凭据；API `/readyz` 必须把 Runner 作为强依赖检查。

## 13 开发先后依赖

| 阶段 | 主要交付 | 依赖 | 交付物 |
| --- | --- | --- | --- |
| P0 | 对象/协议固化 | 技术栈选型、final feature spec | Schema、Context API、Baseline Governance |
| P1 | 项目/版本接入能力 | Source Connectors、Context Engine | Asset Ingestion Pipeline、Historical Baseline Generator |
| P2 | 会话/任务/质量方案 | Intelligence Plane + Agent | Session API、Task Context Builder、Verification Plan |
| P3 | 执行与失败 | Automation Service、Runner、Failure Worker | Playwright Runner Jobs、Run Evidence Store、Failure Reports |
| P4 | 放行与沉淀 | Approval Control、Release Advice | Release Decision UI、Candidate Approval Workflow、Baseline Writer |
| P5 | 运维与治理 | Audit Store、Policy Service、Observability | RBAC 配置、审计看板、监控体系 |

- 建议先完成 P0-P3，形成项目接入、任务分析和 Web 执行闭环；在此基础上再补齐 P4-P5 的审批、沉淀和运维治理能力。
- 随着成熟度提升，可把 worker 按 Context/Impact/Scenario/Failure 进一步分池、把 runner 做成隔离 job、把 OpenGrok/Tree-sitter 解析从实时路径剥离、把 V1 的 PostgreSQL FTS + pgvector 检索投影平滑替换为专用向量/检索层。[文档未明示，此为可演进建议]

上文内容可直接供设计评审和部署讨论使用，若需要我还能把它转成图示版或工程落地清单。
